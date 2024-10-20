import os
import camelot
from pypdf import PdfReader
import re
from config import keyword_patterns
import pandas as pd
from flask import Flask, request, send_file, jsonify
from io import BytesIO
import tempfile

app = Flask(__name__)


# Helper functions
def extract_text_from_pdf(pdf_path):
    reader = PdfReader(pdf_path)
    text = ''
    for page in reader.pages:
        text += page.extract_text()
    return text


def split_text_by_keyword(text, keyword_patterns):
    result = {}
    for keyword_pattern in keyword_patterns:
        keyword_regex = re.compile(keyword_pattern)
        matches = keyword_regex.finditer(text)
        for match in matches:
            keyword = match.group()
            start = match.end()
            end = len(text)
            for next_pattern in keyword_patterns:
                next_match = re.search(next_pattern, text[start:])
                if next_match:
                    end = min(end, start + next_match.start())
            words = text[start:end].split()
            result[keyword] = words
    return result


def extract_tables(file):
    # Save the uploaded file to a temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        file.save(temp_pdf.name)  # Save the uploaded file to the temp file path

        # Extract text from the saved PDF file
        pdf_text = extract_text_from_pdf(temp_pdf.name)
        result = split_text_by_keyword(pdf_text, keyword_patterns)

        # Create a map of keyword to words
        keyword_to_words = {}
        for keyword, words in result.items():
            keyword_to_words[keyword] = set(words)

        tables = camelot.read_pdf(temp_pdf.name, pages='all')

        # Add a mapping of each CSV to a set of all words contained in that CSV
        csv_word_sets = {}
        table_nr_to_csv = {}

        for i, table in enumerate(tables):
            # Flatten the table data and split into words
            words = ' '.join(table.df.values.flatten()).split()
            # Create a set of words for the current table
            csv_word_sets[f'table_{i}'] = set(words)
            table_nr_to_csv[f'table_{i}'] = table

        # Make a pair of keyword to table
        keyword_to_table = {}
        for keyword, words in keyword_to_words.items():
            for table_name, table_words in csv_word_sets.items():
                if table_words.issubset(words):
                    keyword_to_table[keyword] = table_nr_to_csv[table_name]
                    break

        # Use BytesIO to create an in-memory Excel file
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            for keyword, table in reversed(list(keyword_to_table.items())):
                table.df.to_excel(writer, sheet_name=keyword, index=False, header=False)

        # Ensure the file is written and the pointer is at the start
        output.seek(0)

        return output


# Flask routes
@app.route('/extract-tables', methods=['POST'])
def extract_tables_route():
    if 'pdf_file' not in request.files:
        return jsonify({'error': 'No PDF file uploaded'}), 400

    pdf_file = request.files['pdf_file']

    try:
        # Extract tables and create Excel file
        excel_file = extract_tables(pdf_file)

        # Return the file for download
        return send_file(excel_file, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         download_name='tables.xlsx', as_attachment=True)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    # Ensure the output directory exists
    os.makedirs('output', exist_ok=True)
    app.run(debug=True)
