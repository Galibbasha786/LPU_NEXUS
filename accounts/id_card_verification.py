import unicodedata


class OcrUnavailableError(Exception):
    pass


class IdCardReadError(Exception):
    pass


def normalize_id_text(value):
    value = unicodedata.normalize('NFKD', value).casefold()
    return ''.join(character for character in value if character.isalnum())


def _prepare_image(image):
    from PIL import ImageOps

    image = ImageOps.exif_transpose(image).convert('L')
    image = ImageOps.autocontrast(image)
    return image.resize((image.width * 2, image.height * 2))


def _extract_image_text(image, pytesseract, registration_number):
    from PIL import ImageOps

    image = ImageOps.autocontrast(image.convert('L'))
    recognized_text = [
        pytesseract.image_to_string(image, lang='eng', config='--oem 3 --psm 6', timeout=12)
    ]
    normalized_registration_number = normalize_id_text(registration_number)
    if not normalized_registration_number:
        return '\n'.join(recognized_text)

    data = pytesseract.image_to_data(
        image, lang='eng', config='--oem 3 --psm 6',
        output_type=pytesseract.Output.DICT, timeout=12,
    )
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
        recognized_text.append(pytesseract.image_to_string(
            crop, lang='eng', config='--oem 3 --psm 7', timeout=12
        ))
        break

    return '\n'.join(recognized_text)


def _extract_card_text(uploaded_file, registration_number=''):
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
            if document.page_count > 3:
                raise IdCardReadError
            for page in document:
                page_text = page.get_text()
                if page_text:
                    images.append(page_text)
                image_rects = []
                for image_info in page.get_images(full=True):
                    image_rects.extend(page.get_image_rects(image_info))
                unique_rects = list(dict.fromkeys(image_rects))
                for rect in unique_rects[:12]:
                    pixmap = page.get_pixmap(
                        matrix=pymupdf.Matrix(2, 2), clip=rect, alpha=False
                    )
                    images.append(Image.frombytes(
                        'RGB', [pixmap.width, pixmap.height], pixmap.samples
                    ))
                if not unique_rects:
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                    images.append(Image.frombytes(
                        'RGB', [pixmap.width, pixmap.height], pixmap.samples
                    ))
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
    except (UnidentifiedImageError, OSError, RuntimeError, ValueError) as error:
        raise IdCardReadError from error
    finally:
        uploaded_file.seek(position)


def verify_student_id_card(uploaded_file, full_name, registration_number):
    recognized_text = normalize_id_text(_extract_card_text(uploaded_file, registration_number))
    normalized_name = normalize_id_text(full_name)
    normalized_registration_number = normalize_id_text(registration_number)
    return {
        'name_matches': bool(normalized_name and normalized_name in recognized_text),
        'registration_number_matches': bool(
            normalized_registration_number
            and normalized_registration_number in recognized_text
        ),
    }