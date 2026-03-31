# Use a lightweight Python image
FROM python:3.11-slim

# Install system dependencies for OCR
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-hin \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Set working directory inside the container
WORKDIR /app

# Copy all project files into the container
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Command to run your app
# CMD ["python", "app.py"]
EXPOSE 10000
# CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:app"]
CMD ["gunicorn", "--timeout", "300", "-b", "0.0.0.0:10000", "app:app"]