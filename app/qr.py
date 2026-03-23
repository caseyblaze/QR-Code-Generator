import qrcode
from PIL import Image


def generate_qr_png(data: str, dimension: int, color: str, border: int) -> Image.Image:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)

    try:
        image = qr.make_image(fill_color=color, back_color="white").convert("RGB")
    except ValueError as exc:
        raise ValueError("color must be a hex value like #rrggbb or #rgb") from exc
    if dimension:
        image = image.resize((dimension, dimension), Image.NEAREST)
    return image
