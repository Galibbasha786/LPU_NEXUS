import re
import unicodedata

from PIL import ImageOps


MAX_OCR_IMAGE_DIMENSION = 1800
OCR_RETRY_IMAGE_DIMENSION = 1200
OCR_TIMEOUT_SECONDS = 12


class OcrUnavailableError(Exception):
    pass


class IdCardReadError(Exception):
    pass


def normalize_id_text(value):
    value = unicodedata.normalize('NFKD', value).casefold()
    return ''.join(character for character in value if character.isalnum())


def registration_number_matches(recognized_text, registration_number):
    expected = normalize_id_text(registration_number)
    if not expected:
        return False

    normalized_text = normalize_id_text(recognized_text)
    if expected in normalized_text:
        return True

    if not expected.isdigit():
        return False

    digit_confusions = str.maketrans({
        'o': '0', 'q': '9', 'i': '1', 'l': '1', '|': '1', '!': '1',
        's': '5', 'b': '8', 'z': '2',
    })
    number_like = re.compile(r'^[0-9oqil|!sbz]+$')
    for line in recognized_text.casefold().splitlines():
        tokens = re.findall(r'[a-z0-9|!]+', line)
        candidate_tokens = []
        for token in tokens + ['']:
            if number_like.fullmatch(token):
                candidate_tokens.append(token)
                continue
            if candidate_tokens:
                candidate = ''.join(candidate_tokens).translate(digit_confusions)
                if candidate == expected:
                    return True
                candidate_tokens = []
    return False


def _prepare_image(image):
    image = ImageOps.exif_transpose(image).convert('L')
    image = ImageOps.autocontrast(image)
    scale = min(2, MAX_OCR_IMAGE_DIMENSION / max(image.size))
    return image.resize((
        max(1, round(image.width * scale)),
        max(1, round(image.height * scale)),
    ))


def _text_has_expected_fields(text, full_name, registration_number):
    normalized_text = normalize_id_text(text)
    if full_name and normalize_id_text(full_name) not in normalized_text:
        return False
    if registration_number and not registration_number_matches(
        text, registration_number,
    ):
        return False
    return bool(text.strip())


def _run_image_ocr(image, pytesseract, config):
    try:
        return pytesseract.image_to_string(
            image, lang='eng', config=config, timeout=OCR_TIMEOUT_SECONDS,
        ), False
    except RuntimeError as error:
        if str(error) != 'Tesseract process timeout':
            raise

    retry_image = image.copy()
    retry_image.thumbnail((OCR_RETRY_IMAGE_DIMENSION, OCR_RETRY_IMAGE_DIMENSION))
    if retry_image.size == image.size:
        return '', True
    try:
        text = pytesseract.image_to_string(
            retry_image, lang='eng', config=config, timeout=OCR_TIMEOUT_SECONDS,
        )
    except RuntimeError as error:
        if str(error) != 'Tesseract process timeout':
            raise
        return '', True
    return text, True


def _extract_image_text(image, pytesseract, registration_number):
    from PIL import ImageOps

    image = ImageOps.autocontrast(image.convert('L'))
    recognized_text = []
    normalized_registration_number = normalize_id_text(registration_number)
    for page_segmentation_mode in (6, 11):
        text, timed_out = _run_image_ocr(
            image, pytesseract, f'--oem 3 --psm {page_segmentation_mode}',
        )
        recognized_text.append(text)
        if normalized_registration_number and registration_number_matches(
            text, registration_number,
        ):
            return '\n'.join(recognized_text)
        if timed_out:
            return '\n'.join(recognized_text)
    if not normalized_registration_number:
        return '\n'.join(recognized_text)

    try:
        data = pytesseract.image_to_data(
            image, lang='eng', config='--oem 3 --psm 6',
            output_type=pytesseract.Output.DICT, timeout=OCR_TIMEOUT_SECONDS,
        )
    except RuntimeError as error:
        if str(error) == 'Tesseract process timeout':
            return '\n'.join(recognized_text)
        raise
    for index, word in enumerate(data['text']):
        if normalized_registration_number not in normalize_id_text(word):
            continue
        left = data['left'][index]
        top = data['top'][index]
        width = data['width'][index]
        height = data['height'][index]
        crop = image.crop((
            max(0, left - int(image.width * 0.045)),
            max(0, top + max(4, int(height * 0.3))),
            min(image.width, left + width + int(image.width * 0.19)),
            min(image.height, top + max(4, int(height * 0.3)) + int(image.height * 0.19)),
        ))
        crop_text, _ = _run_image_ocr(crop, pytesseract, '--oem 3 --psm 7')
        recognized_text.append(crop_text)
        break

    return '\n'.join(recognized_text)


def _extract_card_text(uploaded_file, registration_number='', full_name=''):
    try:
        import pytesseract
        from PIL import Image, UnidentifiedImageError
    except ImportError as error:
        raise OcrUnavailableError from error

    position = uploaded_file.tell()
    extension = uploaded_file.name.rsplit('.', 1)[-1].lower()
    images = []
    try:
        if extension == 'pdf':
            try:
                import pymupdf
            except ImportError as error:
                raise OcrUnavailableError from error

            document = pymupdf.open(stream=uploaded_file.read(), filetype='pdf')
            try:
                if not document.page_count or document.page_count > 3:
                    raise IdCardReadError
                for page in document:
                    page_text = page.get_text()
                    if page_text:
                        images.append(page_text)
                    if not page_text or not _text_has_expected_fields(
                        page_text, full_name, registration_number,
                    ):
                        max_page_dimension = max(page.rect.width, page.rect.height)
                        if max_page_dimension <= 0:
                            raise IdCardReadError
                        scale = min(2, 3000 / max_page_dimension)
                        pixmap = page.get_pixmap(
                            matrix=pymupdf.Matrix(scale, scale), alpha=False
                        )
                        image = Image.frombytes(
                            'RGB', (pixmap.width, pixmap.height), pixmap.samples
                        )
                        images.append(_prepare_image(image))
            finally:
                document.close()
        else:
            with Image.open(uploaded_file) as image:
                images.append(_prepare_image(image.copy()))

        return '\n'.join(
            image if isinstance(image, str) else _extract_image_text(
                image, pytesseract, registration_number
            )
            for image in images
        )
    except pytesseract.TesseractNotFoundError as error:
        raise OcrUnavailableError from error
    except (
        Image.DecompressionBombError, UnidentifiedImageError, OSError,
        RuntimeError, ValueError,
    ) as error:
        raise IdCardReadError from error
    finally:
        uploaded_file.seek(position)


def verify_student_id_card(uploaded_file, full_name, registration_number):
    extracted_text = _extract_card_text(
        uploaded_file, registration_number, full_name,
    )
    recognized_text = normalize_id_text(extracted_text)
    normalized_name = normalize_id_text(full_name)
    return {
        'name_matches': bool(normalized_name and normalized_name in recognized_text),
        'registration_number_matches': registration_number_matches(
            extracted_text, registration_number,
        ),
    }