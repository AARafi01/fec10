#!/usr/bin/env python3
"""
DUCMC Batch Result Processor
Process multiple registration numbers and export to Excel
"""

import pandas as pd
from ducmc_result_scraper import DUCMCResultScraper, print_result
from datetime import datetime
import configparser
import os
from typing import List

class BatchProcessor:
    def __init__(self, config_file: str = "config.ini"):
        """Initialize batch processor with configuration"""
        self.config = configparser.ConfigParser()
        if os.path.exists(config_file):
            self.config.read(config_file)
        else:
            print(f"Warning: Config file {config_file} not found. Using defaults.")
            self.set_defaults()
    
    def set_defaults(self):
        """Set default configuration"""
        self.config['SETTINGS'] = {
            'HEADLESS': 'False',
            'REQUEST_DELAY': '2',
            'WAIT_TIMEOUT': '10',
            'MIN_DELAY': '3',
            'MAX_DELAY': '7'
        }
        self.config['DEFAULTS'] = {
            'PROGRAM_ID': '14',
            'EXAM_ID': '1563',
            'SESSION_ID': '23'
        }
        self.config['CGPA_CALCULATION'] = {
            'FORMULA': 'custom'
        }
    
    def get_config_value(self, section: str, key: str, default: str = ""):
        """Get configuration value with fallback to default"""
        try:
            return self.config.get(section, key)
        except:
            return default
    
    def read_registration_numbers(self, input_file: str) -> List[str]:
        """
        Read registration numbers from a file
        
        Supports:
        - Text file (.txt): one registration number per line
        - Excel file (.xlsx): reads from first column
        - CSV file (.csv): reads from first column
        """
        file_ext = os.path.splitext(input_file)[1].lower()
        
        if file_ext == '.txt':
            with open(input_file, 'r') as f:
                return [line.strip() for line in f if line.strip()]
        
        elif file_ext in ['.xlsx', '.xls']:
            df = pd.read_excel(input_file)
            return df.iloc[:, 0].astype(str).tolist()
        
        elif file_ext == '.csv':
            df = pd.read_csv(input_file)
            return df.iloc[:, 0].astype(str).tolist()
        
        else:
            raise ValueError(f"Unsupported file format: {file_ext}")
    
    def process_batch(self, registration_numbers: List[str], 
                     output_file: str = None) -> pd.DataFrame:
        """
        Process multiple registration numbers and export to Excel
        
        Args:
            registration_numbers: List of registration numbers
            output_file: Path to output Excel file
        
        Returns:
            DataFrame with all results
        """
        import random
        
        # Get configuration
        headless = self.get_config_value('SETTINGS', 'HEADLESS', 'False').lower() == 'true'
        program_id = self.get_config_value('DEFAULTS', 'PROGRAM_ID', '14')
        exam_id = self.get_config_value('DEFAULTS', 'EXAM_ID', '1563')
        session_id = self.get_config_value('DEFAULTS', 'SESSION_ID', '23')
        formula = self.get_config_value('CGPA_CALCULATION', 'FORMULA', 'custom')
        min_delay = int(self.get_config_value('SETTINGS', 'MIN_DELAY', '3'))
        max_delay = int(self.get_config_value('SETTINGS', 'MAX_DELAY', '7'))
        
        results_list = []
        
        with DUCMCResultScraper(headless=headless) as scraper:
            total = len(registration_numbers)
            
            for idx, reg_no in enumerate(registration_numbers, 1):
                print(f"\n[{idx}/{total}] Processing: {reg_no}")
                
                result = scraper.get_result(
                    registration_no=reg_no,
                    program_id=program_id,
                    exam_id=exam_id,
                    session_id=session_id,
                    cgpa_formula=formula
                )
                
                if 'error' in result:
                    print(f"❌ Error: {result['error']}")
                    results_list.append({
                        'Registration': reg_no,
                        'Status': 'Error',
                        'Error Message': result['error'],
                        'CGPA': None
                    })
                else:
                    print(f"✅ Success - CGPA: {result.get('calculated_cgpa', 'N/A')}")
                    
                    # Prepare data for DataFrame
                    row_data = {
                        'Registration': reg_no,
                        'Name': result['student_info'].get('Student\'s Name', 'N/A'),
                        'College': result['student_info'].get('College Name', 'N/A'),
                        'Program': result['student_info'].get('Program', 'N/A'),
                        'Session': result['student_info'].get('Session', 'N/A'),
                        'Exam Roll': result['student_info'].get('Exam Roll', 'N/A'),
                        'Class Roll': result['student_info'].get('Class Roll', 'N/A'),
                        'Status': result.get('status', 'Unknown'),
                        'CGPA': result.get('calculated_cgpa', None),
                        'Total Subjects': len(result.get('subjects', []))
                    }
                    
                    # Add individual subject grades
                    for subject in result.get('subjects', []):
                        col_name = f"{subject['code']} - Grade"
                        row_data[col_name] = subject['grade']
                        
                        col_name_point = f"{subject['code']} - Point"
                        row_data[col_name_point] = subject['point']
                    
                    results_list.append(row_data)
                
                # Random delay between requests to avoid IP blocking
                if idx < total:
                    delay = random.uniform(min_delay, max_delay)
                    print(f"⏳ Waiting {delay:.1f} seconds before next request...")
                    import time
                    time.sleep(delay)
        
        # Create DataFrame
        df = pd.DataFrame(results_list)
        
        # Export to Excel if output file is specified
        if output_file:
            self.export_to_excel(df, output_file)
        
        return df
    
    def export_to_excel(self, df: pd.DataFrame, output_file: str):
        """Export DataFrame to Excel with formatting"""
        try:
            # Create Excel writer
            with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Results', index=False)
                
                # Get workbook and worksheet
                workbook = writer.book
                worksheet = writer.sheets['Results']
                
                # Auto-adjust column widths
                for column in worksheet.columns:
                    max_length = 0
                    column_letter = column[0].column_letter
                    
                    for cell in column:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    
                    adjusted_width = min(max_length + 2, 50)
                    worksheet.column_dimensions[column_letter].width = adjusted_width
                
                # Format header row
                from openpyxl.styles import Font, PatternFill, Alignment
                
                header_fill = PatternFill(start_color="2F1B72", end_color="2F1B72", fill_type="solid")
                header_font = Font(bold=True, color="FFFFFF")
                
                for cell in worksheet[1]:
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = Alignment(horizontal='center', vertical='center')
            
            print(f"\n✅ Results exported to: {output_file}")
            
        except Exception as e:
            print(f"\n❌ Error exporting to Excel: {e}")
    
    def generate_summary_report(self, df: pd.DataFrame) -> str:
        """Generate a summary report from the results"""
        total = len(df)
        successful = len(df[df['Status'] != 'Error'])
        failed = total - successful
        
        if 'CGPA' in df.columns:
            cgpa_data = df[df['CGPA'].notna()]['CGPA']
            avg_cgpa = cgpa_data.mean() if len(cgpa_data) > 0 else 0
            max_cgpa = cgpa_data.max() if len(cgpa_data) > 0 else 0
            min_cgpa = cgpa_data.min() if len(cgpa_data) > 0 else 0
        else:
            avg_cgpa = max_cgpa = min_cgpa = 0
        
        report = f"""
{'='*70}
BATCH PROCESSING SUMMARY REPORT
{'='*70}
Total Records Processed: {total}
Successful: {successful}
Failed: {failed}

CGPA Statistics:
  Average CGPA: {avg_cgpa:.2f}
  Highest CGPA: {max_cgpa:.2f}
  Lowest CGPA: {min_cgpa:.2f}

Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'='*70}
        """
        
        return report


def main():
    """Main function for batch processing"""
    import argparse
    
    parser = argparse.ArgumentParser(description='DUCMC Batch Result Processor')
    parser.add_argument('-i', '--input', required=True, help='Input file (txt, csv, or xlsx)')
    parser.add_argument('-o', '--output', help='Output Excel file (default: results_TIMESTAMP.xlsx)')
    parser.add_argument('-c', '--config', default='config.ini', help='Configuration file')
    
    args = parser.parse_args()
    
    # Generate default output filename if not provided
    if not args.output:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        args.output = f'results_{timestamp}.xlsx'
    
    # Initialize processor
    processor = BatchProcessor(args.config)
    
    # Read registration numbers
    print(f"Reading registration numbers from: {args.input}")
    try:
        registration_numbers = processor.read_registration_numbers(args.input)
        print(f"Found {len(registration_numbers)} registration numbers")
    except Exception as e:
        print(f"❌ Error reading input file: {e}")
        return
    
    # Process batch
    print("\nStarting batch processing...")
    df = processor.process_batch(registration_numbers, args.output)
    
    # Generate and print summary
    summary = processor.generate_summary_report(df)
    print(summary)
    
    # Save summary to text file
    summary_file = args.output.replace('.xlsx', '_summary.txt')
    with open(summary_file, 'w') as f:
        f.write(summary)
    print(f"Summary saved to: {summary_file}")


if __name__ == "__main__":
    main()