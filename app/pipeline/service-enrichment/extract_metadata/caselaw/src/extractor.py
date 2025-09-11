from bs4 import BeautifulSoup
import re
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MetadataExtractor:
    """
    Extracts structured metadata from a plain text or HTML case law summary file.
    """
    def __init__(self, field_mapping):
        # Mapping from HTML table label to database column name
        self.field_mapping = field_mapping

    def _clean_text(self, text):
        """
        Cleans up extracted text by stripping whitespace, replacing newlines,
        and returning None for common placeholder values.
        """
        if text:
            text = text.strip()
            text = re.sub(r'\s+', ' ', text)
            # If text is a common placeholder, return None so it will be ignored
            if text.lower() in ['n/a', '[not available]', '[n/a]', 'not applicable']:
                return None
        return text

    def _extract_counsel_firm_mapping(self, representation_text):
        """
        Parses the 'Representation' field to create a list of counsel and firm mappings.
        
        Args:
            representation_text (str): The text from the 'Representation' field.
            
        Returns:
            list: A list of dictionaries, where each dict contains 'counsel' and 'law_firm_agency'.
        """
        if not representation_text:
            return []

        final_mappings = []
        counsel_name = None
        
        # Split by newline for text files
        representation_lines = [self._clean_text(line) for line in representation_text.splitlines() if self._clean_text(line)]

        for line in representation_lines:
            if 'For the ' in line or 'Self-represented' in line:
                if counsel_name:
                    final_mappings.append({'counsel': counsel_name, 'law_firm_agency': None})
                counsel_name = None
                if 'Self-represented' in line:
                    counsel_name = line.replace(' (Self-represented)', '')
                    final_mappings.append({'counsel': counsel_name, 'law_firm_agency': 'Self-represented'})
                    counsel_name = None
            elif 'Mr' in line or 'Ms' in line or 'SC' in line:
                if counsel_name:
                    final_mappings.append({'counsel': counsel_name, 'law_firm_agency': None})
                counsel_name = line
            else:
                if counsel_name:
                    final_mappings.append({'counsel': counsel_name, 'law_firm_agency': line})
                    counsel_name = None
        
        if counsel_name:
            final_mappings.append({'counsel': counsel_name, 'law_firm_agency': None})
            
        return final_mappings


    def extract_from_html(self, file_content):
        """
        MODIFIED: This function now handles plain text extraction. The name is kept
        for compatibility with the calling function in main.py.

        Args:
            file_content (str): The raw text content of the summary file.

        Returns:
            tuple: A tuple containing a dictionary of metadata and a list of
                   counsel/firm mappings. Returns (None, None) on failure.
        """
        try:
            metadata = {}
            counsel_firm_mappings = []
            
            # Create a regex pattern from the field mapping keys to find all matches
            # e.g., (Citation|Key issues|Catchwords|...):
            pattern = re.compile(r'(' + '|'.join(re.escape(key) for key in self.field_mapping.keys()) + r'):\s*(.*)', re.IGNORECASE)
            
            lines = file_content.splitlines()
            
            # Use a lookahead to find the content between two field labels
            for i, line in enumerate(lines):
                match = pattern.match(line)
                if match:
                    label = match.group(1).strip()
                    # Find the correctly cased label from the mapping
                    found_label = next((k for k in self.field_mapping if k.lower() == label.lower()), None)

                    if found_label:
                        # Value starts on the same line and can continue on subsequent lines
                        value_lines = [match.group(2).strip()]
                        
                        # Look at the next lines until we find another label or the end of the file
                        for next_line in lines[i+1:]:
                            if pattern.match(next_line):
                                break # Stop when we hit the next known label
                            value_lines.append(next_line.strip())
                        
                        full_value = self._clean_text("\n".join(value_lines).strip())

                        if full_value:
                            db_column = self.field_mapping[found_label]
                            metadata[db_column] = full_value
                            
                            if found_label == "Representation":
                                counsel_firm_mappings = self._extract_counsel_firm_mapping(full_value)

            logging.info("Successfully extracted metadata from text file.")
            return metadata, counsel_firm_mappings

        except Exception as e:
            logging.error(f"An error occurred during text extraction: {e}")
            return None, None
