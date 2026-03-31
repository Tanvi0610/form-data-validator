import os
import sys
import logging
import requests as http_requests
from flask import Flask, request, jsonify
from validator import validate_multiple_documents, process_document
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
# --- TEMP FILE DIRECTORY (IMPORTANT for Render) ---
UPLOAD_FOLDER = '/tmp'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# make logs appear reliably in Render
logging.basicConfig(level=logging.INFO, force=True)
app.logger.addHandler(logging.StreamHandler(sys.stdout))
app.logger.setLevel(logging.INFO)

@app.route('/')
def home():
    return jsonify({"status": "ok", "message": "Validator API is live"}), 200

# @app.route('/validate', methods=['POST'])
# def validate_document_endpoint():
    
#     # --- 1. Get File and Form Data ---
    
#     if 'file' not in request.files:
#         return jsonify({'error': 'No file part in the request.'}), 400
    
#     file = request.files['file']
    
#     # Get the rest of the form data
#     form_data = request.form.to_dict()

#     if file.filename == '':
#         return jsonify({'error': 'No file selected.'}), 400

#     if file:
#         # --- 2. Save File Temporarily ---
#         temp_filepath = os.path.join(UPLOAD_FOLDER, file.filename)
#         file.save(temp_filepath)

#         # --- 3. Call Your "Brain" ---
#         try:
#             # Pass the file path and the form data to your validator
#             validation_result = process_document(temp_filepath, form_data)
#         except Exception as e:
#             # Clean up file even if validation fails
#             os.remove(temp_filepath)
#             return jsonify({'error': f"An error occurred during processing: {e}"}), 500

#         # --- 4. Clean Up and Send Response ---
#         os.remove(temp_filepath) # Delete the temp file
        
#         # Send the result dictionary back to Google Apps Script
#         return jsonify(validation_result)

#     return jsonify({'error': 'Something went wrong.'}), 500


@app.route('/validate', methods=['POST'])
def validate_document_endpoint():
    app.logger.info("=== /validate hit ===")

    form_data = request.form.to_dict() if request.content_type and 'multipart' in request.content_type else (request.json or request.form.to_dict())
    form_data = dict(form_data) or {}

    temp_filepath = os.path.join(UPLOAD_FOLDER, 'upload.pdf')

    try:
        # --- Path 1: file_id provided — download from Google Drive ---
        file_id = form_data.pop('file_id', None)
        if file_id:
            app.logger.info(f"Downloading file from Drive, id={file_id}")
            session = http_requests.Session()
            download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
            resp = session.get(download_url, timeout=(10, 60))

            # Handle Google's virus scan warning page for large files
            if 'text/html' in resp.headers.get('Content-Type', ''):
                # Extract confirmation token and retry
                import re
                token_match = re.search(r'confirm=([0-9A-Za-z_\-]+)', resp.text)
                if token_match:
                    token = token_match.group(1)
                    resp = session.get(f"{download_url}&confirm={token}", timeout=(10, 60))
                else:
                    return jsonify({'error': 'File is not publicly accessible on Google Drive'}), 400

            if resp.status_code != 200:
                return jsonify({'error': f'Failed to download file from Drive: {resp.status_code}'}), 400

            with open(temp_filepath, 'wb') as f:
                f.write(resp.content)

        # --- Path 2: binary file uploaded directly ---
        elif 'file' in request.files:
            file = request.files['file']
            mime_type = file.content_type or ''
            filename = file.filename or ''
            if not filename.lower().endswith('.pdf') and mime_type != 'application/pdf':
                return jsonify({'error': 'Only PDF files allowed'}), 400
            file.save(temp_filepath)

        else:
            return jsonify({'error': 'No file or file_id provided'}), 400

        app.logger.info(f"Saved temp file: {temp_filepath}")

        # --- Validate document ---
        validation_result = process_document(temp_filepath, form_data)
        return jsonify(validation_result)

    except Exception as e:
        app.logger.exception("Processing error")
        return jsonify({'error': str(e)}), 500

    finally:
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)


def download_from_drive(file_id, save_path):
    session = http_requests.Session()
    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    resp = session.get(download_url, timeout=(10, 60))
    if 'text/html' in resp.headers.get('Content-Type', ''):
        import re
        token_match = re.search(r'confirm=([0-9A-Za-z_\-]+)', resp.text)
        if token_match:
            resp = session.get(f"{download_url}&confirm={token_match.group(1)}", timeout=(10, 60))
        else:
            raise Exception('File is not publicly accessible on Google Drive')
    if resp.status_code != 200:
        raise Exception(f'Failed to download file: {resp.status_code}')
    with open(save_path, 'wb') as f:
        f.write(resp.content)


@app.route('/validate-multiple', methods=['POST'])
def validate_multiple_endpoint():
    app.logger.info("=== /validate-multiple hit ===")

    form_data = request.form.to_dict() if request.content_type and 'multipart' in request.content_type else (request.json or request.form.to_dict())
    form_data = dict(form_data) or {}

    # common fields
    name = form_data.get('name', '')
    id_number = form_data.get('id_number', '')
    department = form_data.get('department', '')

    # file ids and doc types
    file_id_1 = form_data.get('file_id_1')
    doc_type_1 = form_data.get('doc_type_1', '')
    file_id_2 = form_data.get('file_id_2')
    doc_type_2 = form_data.get('doc_type_2', '')
    file_id_3 = form_data.get('file_id_3')
    doc_type_3 = form_data.get('doc_type_3', '')

    results = []

    for file_id, doc_type in [(file_id_1, doc_type_1), (file_id_2, doc_type_2), (file_id_3, doc_type_3)]:
        if not file_id or not doc_type:
            continue
        temp_path = os.path.join(UPLOAD_FOLDER, f'upload_{doc_type.replace(" ", "_")}.pdf')
        try:
            download_from_drive(file_id, temp_path)
            result = process_document(temp_path, {
                'name': name,
                'id_number': id_number,
                'department': department,
                'doc_type': doc_type
            })
            results.append(result)
        except Exception as e:
            results.append({'doc_type': doc_type, 'status': str(e), 'validation_passed': False})
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    all_passed = all(r['validation_passed'] for r in results)
    return jsonify({'validation_passed': all_passed, 'results': results})


if __name__ == '__main__':
    # Run the server. 
    # 'debug=True' reloads the server when you save changes.
    # 'host='0.0.0.0'' makes it accessible on your network (optional).
    # app.run(host='0.0.0.0', port=5000, debug=True)

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
