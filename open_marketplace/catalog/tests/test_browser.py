from contextlib import contextmanager
from importlib import import_module
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import expect, sync_playwright

from open_marketplace.catalog.tests.fixtures import CatalogTestCase


class CatalogBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        self.fixture = CatalogTestCase(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def cookies(self, registry):
        client = import_module("open_marketplace.catalog.tests.test_web").CatalogWebTests.client_for(self.fixture, registry)
        return [{"name": settings.SESSION_COOKIE_NAME, "value": client.cookies[settings.SESSION_COOKIE_NAME].value, "url": self.live_server_url}]

    @contextmanager
    def browser(self, registry, *, width=1200):
        cookies = self.cookies(registry)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": width, "height": 800})
            context.add_cookies(cookies)
            page = context.new_page()
            page.set_default_timeout(10000)
            try:
                yield page
            finally:
                browser.close()

    def test_staff_pages_have_one_main_heading(self):
        with self.browser(self.fixture.staff_registry) as page:
            page.goto(self.live_server_url + "/admin/")
            paths = page.locator('.staff-nav a[href^="/admin/"]').evaluate_all("links => links.map(link => link.getAttribute('href'))")
            for path in dict.fromkeys(["/admin/", *paths]):
                with self.subTest(path=path):
                    response = page.goto(self.live_server_url + path)
                    self.assertEqual(response.status, 200)
                    expect(page.get_by_role("heading", level=1)).to_have_count(1)

    def test_skip_link_moves_keyboard_focus_to_page_content(self):
        with self.browser(self.fixture.buyer_registry) as page:
            for path in ("/catalog/", "/security/", "/seller/applications/"):
                with self.subTest(path=path):
                    page.goto(self.live_server_url + path)
                    page.keyboard.press("Tab")
                    expect(page.get_by_role("link", name="К содержимому", exact=True)).to_be_focused()
                    page.keyboard.press("Enter")
                    expect(page.get_by_role("main")).to_be_focused()

    def test_mobile_forms_keep_touch_targets_inside_the_viewport(self):
        with self.browser(self.fixture.buyer_registry, width=360) as page:
            page.context.clear_cookies()
            for path in ("/login/", "/register/", "/identity/password-reset/"):
                with self.subTest(path=path):
                    page.goto(self.live_server_url + path)
                    field = page.locator('main input:not([type="hidden"])').first.bounding_box()
                    button = page.locator('main button[type="submit"]').first.bounding_box()
                    self.assertGreaterEqual(field["height"], 44)
                    self.assertGreaterEqual(button["height"], 44)
                    self.assertGreaterEqual(field["x"], 0)
                    self.assertLessEqual(field["x"] + field["width"], 360)
                    self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))

    def test_desktop_results_remain_beside_filters(self):
        self.fixture.product()
        with self.browser(self.fixture.buyer_registry, width=1280) as page:
            page.goto(self.live_server_url + "/catalog/")
            filters = page.locator("[data-search-form]").bounding_box()
            results = page.locator("[data-results]").bounding_box()
            self.assertLessEqual(filters["x"] + filters["width"], results["x"])
            self.assertGreater(results["width"], filters["width"])
            expect(page.locator("[data-item-id]")).to_have_count(1)

    def test_text_waits_for_submit_and_filter_applies_typed_text_on_mobile(self):
        self.fixture.product()
        with self.browser(self.fixture.buyer_registry, width=390) as page:
            page.goto(self.live_server_url + "/catalog/")
            field = page.locator("#catalog-q")
            field.fill("Куртка")
            page.wait_for_timeout(300)
            self.assertEqual(urlsplit(page.url).query, "")
            page.locator('[name="f.color"][value="Красный"]').check()
            page.wait_for_url("**/catalog/?**")
            self.assertEqual(parse_qs(urlsplit(page.url).query)["q"], ["Куртка"])
            expect(page.locator("[data-item-id]")).to_have_count(1)
            expect(page.locator('[name="f.size"][value="M"]')).to_be_disabled()
            self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))

    def test_scroll_error_keeps_items_retry_and_back_restore_fresh_window(self):
        for index in range(23):
            self.fixture.product(title=f"Товар {index:03d}")
        with self.browser(self.fixture.buyer_registry) as page:
            page.route("**/catalog/?**", lambda route: route.abort() if "fragment=1" in route.request.url else route.continue_())
            page.goto(self.live_server_url + "/catalog/")
            expect(page.locator("[data-item-id]")).to_have_count(20)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            expect(page.locator("[data-load-error]")).to_be_visible()
            expect(page.locator("[data-item-id]")).to_have_count(20)
            page.unroute("**/catalog/?**")
            page.locator("[data-retry]").click()
            expect(page.locator("[data-item-id]")).to_have_count(23)
            last = page.locator("[data-item-id] h2 a").last
            last.scroll_into_view_if_needed()
            offset = page.evaluate("window.scrollY")
            last.click()
            expect(page.locator("[data-product]")).to_be_visible()
            page.go_back()
            expect(page.locator("[data-item-id]")).to_have_count(23)
            page.wait_for_function("expected => window.scrollY >= expected - 160", arg=offset)
            self.assertEqual(page.locator("[data-item-id]").evaluate_all("nodes => new Set(nodes.map(n => n.dataset.itemId)).size"), 23)
            card = page.locator("[data-item-id]").last
            card.locator("img").evaluate("image => image.dispatchEvent(new Event('error'))")
            expect(card.locator("[data-photo-error]")).to_be_visible()

    def test_seller_creates_real_card_uploads_photo_and_publishes_in_browser(self):
        image = self.fixture.image().read()
        with self.browser(self.fixture.seller_registry) as page:
            page.goto(self.live_server_url + "/catalog/own/new/")
            page.get_by_role("button", name="Создать", exact=True).click()
            page.wait_for_url("**/catalog/own/*/")
            product_url = page.url
            main = page.locator('form:has(input[name="action"][value="save_product"])')
            main.locator('[name="title"]').fill("Куртка из браузера")
            main.locator('[name="description"]').fill("Тестовое фото, варианты и цена")
            main.locator('[name="category_id"]').select_option(str(self.fixture.category_id))
            main.get_by_role("button").click()
            upload = page.locator('form:has(input[value="upload_photo"])')
            upload.locator('input[type="file"]').set_input_files({"name": "fixture.png", "mimeType": "image/png", "buffer": image})
            upload.locator('[name="attested"]').check()
            upload.get_by_role("button", name="Загрузить фото", exact=True).click()
            variant = page.locator('form:has(input[value="add_variant"])')
            variant.locator('[name="label"]').fill("Красный S")
            variant.locator('[name="attr_color"]').select_option("Красный")
            variant.locator('[name="attr_size"]').select_option("S")
            variant.locator('[name="photo_ids"]').check()
            variant.get_by_role("button").click()
            price = page.locator('form:has(input[value="set_price"])')
            price.locator('[name="price"]').fill("125,50")
            price.get_by_role("button").click()
            stock = page.locator('form:has(input[value="set_stock"])')
            stock.locator('[name="quantity"]').fill("3")
            stock.get_by_role("button").click()
            page.get_by_role("button", name="Опубликовать", exact=True).click()
            page.goto(product_url.replace("/own/", "/p/"))
            expect(page.get_by_role("heading", name="Куртка из браузера", exact=True)).to_be_visible()
            expect(page.locator(".variant-detail")).to_contain_text("125,50 ₽")
            page.wait_for_function("Array.from(document.querySelectorAll('.gallery img')).every(image => image.complete && image.naturalWidth > 0)")

    def test_failed_image_is_not_replaced_by_another_gallery_or_no_photos_message(self):
        product, variant, photo = self.fixture.product()
        with self.browser(self.fixture.buyer_registry) as page:
            page.route("**/catalog/photo/**", lambda route: route.abort())
            page.goto(self.live_server_url + f"/catalog/p/{product}/?variant={variant}")
            expect(page.locator(".gallery [data-photo-error]")).to_be_visible()
            expect(page.get_by_text("Для этого варианта нет доступных фотографий", exact=True)).to_have_count(0)
            page.unroute("**/catalog/photo/**")
            page.locator(".gallery [data-photo-retry]").click()
            page.wait_for_function("document.querySelector('.gallery img').naturalWidth > 0")

    def test_staff_can_revoke_access_and_buyer_reload_removes_content(self):
        self.fixture.product(title="Недоступно после отзыва")
        staff_cookies = self.cookies(self.fixture.staff_registry)
        with self.browser(self.fixture.buyer_registry) as buyer:
            buyer.goto(self.live_server_url + "/catalog/")
            expect(buyer.locator("[data-item-id]")).to_have_count(1)
            staff_context = buyer.context.browser.new_context()
            staff_context.add_cookies(staff_cookies)
            staff = staff_context.new_page()
            staff.goto(self.live_server_url + "/catalog/manage/")
            form = staff.locator('form:has(input[value="participant"])')
            form.locator('[name="email"]').fill(self.fixture.buyer.email)
            form.locator('[name="allowed"]').uncheck()
            form.get_by_role("button").click()
            buyer.reload()
            expect(buyer.locator("[data-item-id]")).to_have_count(0)
            expect(buyer.locator("body")).not_to_contain_text("Недоступно после отзыва")
            staff_context.close()
