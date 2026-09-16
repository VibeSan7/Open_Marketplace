from open_marketplace.verification.demo_storefront import load_manifest


def get_demo_image_credits():
    return [{"image": item["image"], **item["credit"]} for item in load_manifest()["products"]]
