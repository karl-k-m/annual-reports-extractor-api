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

def extract_balance_table(file):
    """
    Extract only table with the keyword "Bilanss"
    :param file: PDF file
    :return: Pandas DataFrame
    """
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

        # Extract the table with the keyword "Bilanss"
        balance_table = keyword_to_table.get('Bilanss')
        if balance_table is None:
            raise ValueError('Table with keyword "Bilanss" not found')

        return balance_table.df

def combine_csvs(dfs, filenames):
    """
    Combine the DataFrames and rename columns to the respective filenames.
    :param dfs: List of pandas DataFrames
    :param filenames: List of filenames corresponding to the DataFrames
    :return: Combined DataFrame
    """
    combined_df = dfs[0]
    combined_df.columns = [combined_df.columns[0]] + [f"{filenames[0]}_{col}" for col in combined_df.columns[1:]]

    for df, filename in zip(dfs[1:], filenames[1:]):
        # Rename the columns of the current DataFrame
        df.columns = [df.columns[0]] + [f"{filename}_{col}" for col in df.columns[1:]]
        # Merge with the combined DataFrame
        combined_df = pd.merge(combined_df, df, on=combined_df.columns[0], how='outer')

    return combined_df

@app.route('/combine-csvs', methods=['POST'])
def combine_csvs_from_pdfs():
    """
    Combine balance tables from uploaded PDF files and include filenames in the column names.
    """
    # Check if files are uploaded
    if 'pdf_files' not in request.files:
        return jsonify({'error': 'No PDF files uploaded'}), 400

    pdf_files = request.files.getlist('pdf_files')
    filenames = [pdf_file.filename for pdf_file in pdf_files]  # Extract filenames

    try:
        # Extract the balance tables from the PDF files
        balance_tables = [extract_balance_table(pdf_file) for pdf_file in pdf_files]

        # For each table, remove columns with any row containing "Lisa"
        for table in balance_tables:
            for col in table.columns:
                if table[col].str.contains('Lisa').any():
                    table.drop(col, axis=1, inplace=True)

        # Combine the balance tables with filenames
        combined_df = combine_csvs(balance_tables, filenames)

        # Use BytesIO to create an in-memory CSV file
        output = BytesIO()
        combined_df.to_csv(output, index=False)

        # Ensure the file is written and the pointer is at the start
        output.seek(0)

        return send_file(output, mimetype='text/csv', download_name='combined_balance_tables.csv', as_attachment=True)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
