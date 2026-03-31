import re
from difflib import SequenceMatcher
from pdf2image import convert_from_path
import pytesseract
from template_validator import run_template_checks


def fuzzy_match(a, b, threshold=0.60):
    return SequenceMatcher(None, a, b).ratio() >= threshold

# Optional if Tesseract is not in PATH:
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


def process_document(pdf_path, form_data):
    """
    Validates a single PDF document against its expected form data.
    """
    print(f"\n📄 Processing {form_data.get('doc_type')} for {form_data.get('name')}")

    try:
        images = convert_from_path(
            pdf_path,
            first_page=1,
            last_page=1,
            dpi=400,
            grayscale=True,
            poppler_path=r"C:\Users\TANVI\Downloads\Release-25.12.0-0\poppler-25.12.0\Library\bin"
        )
    except Exception as e:
        return {
            'doc_type': form_data.get('doc_type'),
            'status': f"Error: Could not read PDF file. {e}",
            'validation_passed': False
        }

    full_text = ""
    for img in images:
        full_text += pytesseract.image_to_string(img, lang='eng+hin', config='--psm 3')

    full_text = full_text.lower()
    print(f"🔍 OCR extracted text:\n{full_text[:500]}")  # log first 500 chars
    name_from_form = form_data.get('name', '').lower()

    # Flexible identifier field names
    id_field = str(form_data.get('id_number') or form_data.get('roll_number') or form_data.get('registration_number') or '')
    id_field = id_field.lower().replace(' ', '')
    expected_doc_type = form_data.get('doc_type', '').lower()

    # --- Document-specific validation rules ---
    doc_rules = {
        'aadhaar card': ['aadhaar', 'आधार', 'भारत सरकार', 'goverment of india'],
        'adhaar card': ['aadhaar', 'आधार', 'uidai', 'unique identification', 'enrollment no', 'vid:'],
        'pan card': ['income tax department', 'permanent account number', 'pan'],
        'marksheet': ['marksheet', 'grade', 'university', 'board'],
        'birth certificate': ['birth certificate', 'date of birth', 'dob'],
        'college id': ['college','id','university','student']
    }

    # --- Aadhaar structural validation ---
    aadhaar_types = ('aadhaar card', 'adhaar card')
    if expected_doc_type in aadhaar_types:
        missing = []
        if 'government of india' not in full_text and 'भारत सरकार' not in full_text:
            missing.append('Government of India header')
        if not any(k in full_text for k in ['female', 'male', 'महिला', 'पुरुष']):
            missing.append('gender field')
        # check DOB in any format: yyyy-mm-dd, dd-mm-yyyy, dd/mm/yyyy
        import re as _re
        dob_found = (
            any(k in full_text for k in ['dob', 'date of birth', 'जन्म']) or
            bool(_re.search(r'\d{4}-\d{2}-\d{2}', full_text)) or
            bool(_re.search(r'\d{2}-\d{2}-\d{4}', full_text)) or
            bool(_re.search(r'\d{2}/\d{2}/\d{4}', full_text))
        )
        if not dob_found:
            missing.append('date of birth field')
        if 'xxxx' not in full_text and 'aadhaar' not in full_text:
            missing.append('Aadhaar number')
        if missing:
            return {'doc_type': expected_doc_type,
                    'status': f"Invalid Aadhaar: missing {', '.join(missing)}.",
                    'validation_passed': False}

    # Check document keyword (non-Aadhaar)
    keywords = doc_rules.get(expected_doc_type, [])
    if expected_doc_type not in aadhaar_types:
        if not any(k in full_text for k in keywords):
            return {'doc_type': expected_doc_type,
                    'status': f"Mismatch: '{expected_doc_type}' keywords not found.",
                    'validation_passed': False}

    # Check name using fuzzy match to handle OCR misreads
    if name_from_form:
        name_found = name_from_form in full_text or any(
            fuzzy_match(name_from_form, full_text[i:i+len(name_from_form)])
            for i in range(len(full_text) - len(name_from_form) + 1)
        )
        if not name_found:
            return {'doc_type': expected_doc_type,
                    'status': f"Mismatch: Name '{name_from_form}' not found.",
                    'validation_passed': False}

    # Check ID number or Roll number (skip for marksheet)
    if expected_doc_type != 'marksheet':
        if id_field:
            clean_text = full_text.replace(' ', '')
            if expected_doc_type in ('aadhaar card', 'adhaar card'):
                # use aadhaar_number field, skip if not provided
                aadhaar_num = str(form_data.get('aadhaar_number', '')).strip()
                if not aadhaar_num:
                    id_found = True  # skip check if no aadhaar number provided
                else:
                    id_last4 = aadhaar_num[-4:]
                    id_found = id_last4 in clean_text
            else:
                # fuzzy match for college ID since OCR misreads digits
                id_found = id_field in clean_text or any(
                    fuzzy_match(id_field, clean_text[i:i+len(id_field)], threshold=0.80)
                    for i in range(max(len(clean_text) - len(id_field) + 1, 1))
                )
            if not id_found:
                return {'doc_type': expected_doc_type,
                        'status': f"Mismatch: ID '{id_field}' not found.",
                        'validation_passed': False}

    # Check department (college ID and marksheet)
    if expected_doc_type in ('college id', 'marksheet'):
        department = form_data.get('department', '').lower().strip()
        if department:
            # for marksheet, also check first word only (e.g. "computer" from "computer engineering")
            dept_first_word = department.split()[0] if department else ''
            dept_found = (
                department in full_text or
                dept_first_word in full_text or
                any(fuzzy_match(department, full_text[i:i+len(department)])
                    for i in range(len(full_text) - len(department) + 1))
            )
            if not dept_found:
                return {'doc_type': expected_doc_type,
                        'status': f"Mismatch: Department '{department}' not found.",
                        'validation_passed': False}

    # --- OCR checks passed — now run template-based checks ---
    template_results = run_template_checks(images[0], expected_doc_type)

    alignment_status = template_results.get('alignment_status')
    logo_matched = template_results.get('logo_matched')
    photo_present = template_results.get('photo_present')

    # Strict: fail if alignment too low for college ID only
    if expected_doc_type == 'college id' and alignment_status == 'suspicious':
        return {
            'doc_type': expected_doc_type,
            'status': 'Invalid: Document layout does not match expected template.',
            'validation_passed': False,
            **template_results
        }

    # Strict: fail if logo explicitly didn't match (skip for marksheet)
    if expected_doc_type != 'marksheet' and logo_matched is False:
        return {
            'doc_type': expected_doc_type,
            'status': 'Invalid: Logo not matched.',
            'validation_passed': False,
            **template_results
        }

    # Strict: fail if photo not found (skip for marksheet)
    if expected_doc_type != 'marksheet' and photo_present is False:
        return {
            'doc_type': expected_doc_type,
            'status': 'Invalid: Photo not detected in expected region.',
            'validation_passed': False,
            **template_results
        }

    # Suspicious if alignment is low but don't fail
    suspicious = alignment_status == 'suspicious'

    return {
        'doc_type': expected_doc_type,
        'status': f"Valid: {expected_doc_type} matches the form data." + (" (Suspicious layout)" if suspicious else ""),
        'validation_passed': True,
        'suspicious': suspicious,
        **template_results
    }


def validate_multiple_documents(form_data):
    """
    Takes multiple document entries and validates each.
    """
    results = []
    documents = form_data.get("documents", [])

    for doc in documents:
        pdf_path = doc.get("pdf_path")
        if not pdf_path:
            results.append({'doc_type': doc.get("doc_type"), 'status': "No file path provided.", 'validation_passed': False})
            continue
        result = process_document(pdf_path, doc)
        results.append(result)

    return results


# --- Example usage ---
if __name__ == '__main__':
    form_data = {
        "documents": [
            {
                "doc_type": "Aadhaar Card",
                "pdf_path": "aadhaar.pdf",
                "name": "Anushree Kamath",
                "id_number": "973590859427"
            },
            {
                "doc_type": "PAN Card",
                "pdf_path": "pan.pdf",
                "name": "Anushree Kamath",
                "id_number": "MVKPK5101M"
            },
            {
                "doc_type": "Marksheet",
                "pdf_path": "marksheet.pdf",
                "name": "Anushree Kamath",
                "roll_number": "15160071"
            }
        ]
    }

    all_results = validate_multiple_documents(form_data)
    print("\n--- Final Validation Report ---")
    for r in all_results:
        print(f"{r['doc_type']}: {r['status']}")