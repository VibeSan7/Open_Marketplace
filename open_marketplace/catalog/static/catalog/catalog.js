(function () {
  const search = document.querySelector("[data-catalog-search]");
  const form = document.querySelector("[data-search-form]");

  if (form) {
    form.querySelectorAll("[data-auto-submit]").forEach((control) => {
      control.addEventListener("change", () => form.requestSubmit());
    });
  }

  document.querySelectorAll("[data-formset]").forEach((set) => {
    const total = set.querySelector("[name$='-TOTAL_FORMS']");
    const rows = set.querySelector("[data-formset-rows]");
    const add = set.querySelector("[data-add-row]");
    if (!total || !rows || !add) return;
    const bindRemove = (row) => row.querySelector("[data-remove-row]")?.addEventListener("click", () => {
      row.querySelector("[name$='-DELETE']")?.setAttribute("checked", "checked");
      row.hidden = true;
    });
    rows.querySelectorAll("[data-formset-row]").forEach(bindRemove);
    add.addEventListener("click", () => {
      const index = Number(total.value);
      if (index >= 50) return;
      const source = rows.querySelector("[data-formset-row]");
      const row = source.cloneNode(true);
      row.hidden = false;
      row.innerHTML = row.innerHTML.replaceAll(/attributes-\d+/g, "attributes-" + index);
      row.querySelectorAll("input, textarea").forEach((input) => {
        if (input.type === "checkbox") input.checked = false;
        else input.value = "";
      });
      rows.appendChild(row);
      total.value = index + 1;
      bindRemove(row);
    });
  });

  function photoError(image) {
    image.hidden = true;
    const error = image.parentElement.querySelector("[data-photo-error]") || image.closest("article, figure")?.querySelector("[data-photo-error]");
    if (error) error.hidden = false;
  }
  document.addEventListener("error", event => {
    if (event.target.matches?.("[data-photo]")) photoError(event.target);
  }, true);
  document.querySelectorAll("[data-photo]").forEach(image => {
    if (image.complete && image.naturalWidth === 0) photoError(image);
  });
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-photo-retry]");
    if (!button) return;
    const image = button.closest("figure, article")?.querySelector("[data-photo]");
    if (!image) return;
    image.hidden = false;
    button.closest("[data-photo-error]").hidden = true;
    image.src = image.src.split("?")[0] + "?retry=" + Date.now();
  });

  document.querySelectorAll("[data-share]").forEach((button) => {
    button.addEventListener("click", async () => {
      const url = button.closest("[data-product]")?.dataset.shareUrl || window.location.href;
      try {
        await navigator.clipboard.writeText(new URL(url, window.location.href).href);
        button.textContent = "Ссылка скопирована";
      } catch {
        button.textContent = "Скопируйте ссылку из адресной строки";
      }
    });
  });
  document.querySelectorAll("[data-share-search]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(new URL(search.dataset.appliedUrl, window.location.href).href);
        button.textContent = "Ссылка скопирована";
      } catch {
        button.textContent = "Скопируйте ссылку из адресной строки";
      }
    });
  });

  document.querySelectorAll("[data-gallery]").forEach((gallery) => {
    const main = gallery.querySelector("[data-gallery-main]");
    if (!main) return;
    gallery.querySelectorAll("[data-gallery-thumb]").forEach((thumb) => {
      thumb.addEventListener("click", () => {
        main.src = thumb.dataset.gallerySrc;
        main.alt = thumb.querySelector("img")?.alt || main.alt;
        gallery.querySelectorAll("[data-gallery-thumb]").forEach((item) => {
          const selected = item === thumb;
          item.classList.toggle("is-selected", selected);
          item.setAttribute("aria-pressed", String(selected));
        });
      });
    });
  });

  const stateKey = "catalog-navigation-state";
  if (!search) return;
  let saved = null;
  try { saved = JSON.parse(sessionStorage.getItem(stateKey) || "null"); } catch { /* No saved navigation. */ }
  const navigation = performance.getEntriesByType("navigation")[0]?.type;
  const restoring = saved?.url === window.location.href && (navigation === "back_forward" || navigation === "reload");
  const desiredCount = restoring ? saved.count : 0;
  const results = search.querySelector("[data-results]");
  const items = search.querySelector("[data-items]");
  const sentinel = document.createElement("div");
  sentinel.dataset.sentinel = "true";
  results.appendChild(sentinel);
  let cursor = results.querySelector("[data-next-cursor]")?.content || "";
  let loading = false;
  let failed = false;
  const seen = new Set(Array.from(items.querySelectorAll("[data-item-id]"), item => item.dataset.itemId));
  const error = results.querySelector("[data-load-error]");
  const status = results.querySelector("[data-load-status]");

  async function loadNext() {
    if (loading || !cursor || failed) return false;
    loading = true;
    error.hidden = true;
    status.textContent = "Загружаем…";
    const url = new URL(search.dataset.appliedUrl, window.location.origin);
    url.searchParams.set("cursor", cursor);
    url.searchParams.set("fragment", "1");
    try {
      const response = await fetch(url, {headers: {"X-Requested-With": "XMLHttpRequest"}});
      if (response.redirected || response.status === 401 || response.status === 403) {
        items.replaceChildren();
        cursor = "";
        error.textContent = "Доступ к каталогу больше не подтверждён. Войдите повторно.";
        error.hidden = false;
        return false;
      }
      if (!response.ok) throw new Error("load failed");
      const parsed = new DOMParser().parseFromString(await response.text(), "text/html");
      if (!parsed.querySelector("[data-results]")) throw new Error("invalid page");
      const next = parsed.querySelector("[data-next-cursor]")?.content || "";
      if (next && next === cursor) throw new Error("page did not advance");
      parsed.querySelectorAll("[data-item-id]").forEach(item => {
        if (!seen.has(item.dataset.itemId)) {
          seen.add(item.dataset.itemId);
          items.appendChild(item);
        }
      });
      cursor = next;
      return true;
    } catch {
      failed = true;
      error.hidden = false;
      return false;
    } finally {
      loading = false;
      status.textContent = "";
    }
  }

  const observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) loadNext();
  }, {rootMargin: "500px"});
  results.querySelector("[data-retry]").addEventListener("click", () => {
    failed = false;
    loadNext();
  });
  (async () => {
    while (seen.size < desiredCount && cursor) {
      if (!await loadNext()) break;
    }
    if (restoring) requestAnimationFrame(() => window.scrollTo(0, saved.offset || 0));
    observer.observe(sentinel);
  })();

  function saveNavigation() {
    sessionStorage.setItem(stateKey, JSON.stringify({url: window.location.href, offset: window.scrollY, count: seen.size}));
  }
  form.addEventListener("submit", () => sessionStorage.removeItem(stateKey));
  window.addEventListener("pagehide", saveNavigation);
  window.addEventListener("pageshow", event => {
    if (event.persisted) {
      search.hidden = true;
      window.location.reload();
    }
  });
  let hiddenAt = 0;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      hiddenAt = Date.now();
      saveNavigation();
    } else if (hiddenAt && Date.now() - hiddenAt > 1000) {
      search.hidden = true;
      window.location.reload();
    }
  });
})();
