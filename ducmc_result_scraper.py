#!/usr/bin/env python3
"""
DU Crack
Automates form filling and GPA calculation from https://ducmc.du.ac.bd/result.php
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time
import re
from typing import List, Dict, Tuple
from fpdf import FPDF


# Course data with credits for accurate GPA calculation
COURSES_DATA = {
    "CSE-1101": 2.0, "CSE-1102": 3.0, "EEE-1103": 3.0, "CHE-1104": 3.0,
    "MATH-1105": 3.0, "SS-1106": 2.0, "CSE-1111": 1.5, "EEE-1113": 1.5,
    "CHE-1114": 1.5,  # Semester 1
    "CSE-1201": 3.0, "CSE-1202": 3.0, "PHY-1203": 3.0, "MATH-1204": 3.0,
    "ENG-1205": 2.0, "CSE-1211": 3.0, "CSE-1212": 1.5, "PHY-1213": 1.5,
    "ENG-1215": 1.5,  # Semester 2
    "CSE-2101": 3.0, "CSE-2102": 3.0, "CSE-2103": 3.0, "EEE-2104": 3.0,
    "MATH-2105": 3.0, "SS-2106": 2.0, "CSE-2111": 1.5, "CSE-2112": 1.5,
    "CSE-2113": 1.5, "EEE-2114": 0.75,  # Semester 3
    "CSE-2201": 3.0, "CSE-2202": 3.0, "CSE-2203": 3.0, "CSE-2204": 3.0,
    "CSE-2205": 2.0, "CSE-2211": 1.5, "CSE-2212": 1.5, "CSE-2213": 0.75,
    "CSE-2216": 1.5,  # Semester 4
    "CSE-3101": 3.0, "CSE-3102": 3.0, "CSE-3103": 3.0, "CSE-3104": 3.0,
    "MATH-3105": 3.0, "CSE-3111": 1.5, "CSE-3112": 0.75, "CSE-3113": 1.5,
    "CSE-3116": 0.75,  # Semester 5
    "CSE-3201": 3.0, "CSE-3202": 3.0, "CSE-3203": 3.0, "CSE-3204": 3.0,
    "STAT-3205": 3.0, "CSE-3211": 1.5, "CSE-3212": 0.75, "CSE-3216": 1.5,
    "ENG-3217": 0.75,  # Semester 6
    "CSE-4101": 3.0, "CSE-4102": 3.0, "SS-4103": 2.0, "CSE-4111": 1.5,
    "CSE-4113": 1.5, "CSE-4114": 2.0,  # Semester 7
    "ECO-4201": 2.0, "CSE-4202": 2.0, "SS-4203": 2.0, "CSE-4214": 4.0,  # Semester 8
}


class DUCMCResultScraper:
    @staticmethod
    def fetch_available_exams_requests(program_id: str = "14") -> List[Dict]:
        """Fetch available exams dynamically via HTTP GET requests"""
        import requests
        from bs4 import BeautifulSoup
        url = f"https://ducmc.du.ac.bd/ajax/get_program_by_exam.php?program_id={program_id}&pedata=99"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                return []
            soup = BeautifulSoup(response.text, 'html.parser')
            exams = []
            for option in soup.find_all('option'):
                val = option.get('value')
                text = option.text.strip()
                if val and text and "Select" not in text:
                    exams.append({
                        'id': val,
                        'name': text
                    })
            return exams
        except Exception as e:
            print(f"Error fetching exams via requests: {e}")
            return []

    @staticmethod
    def get_result_requests(registration_no: str, program_id: str = "14", exam_id: str = "1563", session_id: str = "23") -> Dict:
        """Fetch and extract student result via HTTP POST requests (stripped of dashes)"""
        import requests
        from bs4 import BeautifulSoup
        import re
        
        # Strip all non-alphanumeric characters to match browser numeric validation (no dashes!)
        reg_clean = re.sub(r'[^0-9]', '', registration_no)
        
        # If the registration is exactly a 3-digit registration and default session_id is 23, use session id 22
        if session_id == "23" and len(reg_clean) == 3:
            session_id = "22"
        
        url = "https://ducmc.du.ac.bd/ajax/get_program_by_exam.php"
        payload = {
            'reg_no': reg_clean,
            'pro_id': program_id,
            'sess_id': session_id,
            'exam_id': exam_id,
            'gdata': '99'
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
        }
        try:
            response = requests.post(url, data=payload, headers=headers, timeout=15)
            if response.status_code != 200:
                return {'error': f'HTTP Error {response.status_code}'}
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            output_div = soup.find(id="outputspass")
            if output_div and output_div.text.strip():
                return {'error': output_div.text.strip()}
                
            result_data = {
                'student_info': {},
                'subjects': [],
                'status': 'Unknown'
            }
            
            info_table = soup.find('table', class_='table table-bordered')
            if not info_table:
                return {'error': 'Student result details table not found on page'}
                
            for row in info_table.find_all('tr'):
                cells = row.find_all(['th', 'td'])
                if len(cells) >= 2:
                    key = cells[0].text.strip()
                    value = cells[1].text.strip()
                    if key:
                        result_data['student_info'][key] = value
                        
            subject_table = soup.find('table', width='100%', border='1')
            if not subject_table:
                return {'error': 'Grades subject table not found on page'}
                
            rows = subject_table.find_all('tr')[1:]
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 5:
                    grade = cells[3].text.strip()
                    point_str = cells[4].text.strip()
                    if grade.upper() == 'F' or point_str.upper() == 'F' or 'FAIL' in grade.upper():
                        point_str = '0.0'
                    subject = {
                        'sl': cells[0].text.strip(),
                        'code': cells[1].text.strip(),
                        'title': cells[2].text.strip(),
                        'grade': grade,
                        'point': point_str,
                        'status': 'FAIL' if grade.upper() == 'F' or 'FAIL' in grade.upper() else 'PASS'
                    }
                    result_data['subjects'].append(subject)
                    
            status_div = soup.find('div', style=lambda v: v and 'text-align: center' in v and 'font-size: 25px' in v)
            if status_div:
                result_data['status'] = status_div.text.strip()
                
            return result_data
        except Exception as e:
            return {'error': f'Requests scraping error: {str(e)}'}

    def __init__(self, headless: bool = False):
        """Initialize the scraper with Chrome webdriver"""
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 10)
        self.url = "https://ducmc.du.ac.bd/result.php"
    
    def fill_form(self, registration_no: str, program_id: str = "14", exam_id: str = "1563", session_id: str = "23"):
        """
        Fill the result search form
        
        Args:
            registration_no: Student registration number
            program_id: Program ID (default: "14" for B.Sc. in Computer Science and Engineering)
            exam_id: Exam ID (default: "1563" for 2nd year 1st Semester 2024)
            session_id: Session ID (default: "23" for 2022-2023)
        """
        try:
            self.driver.get(self.url)
            time.sleep(2)
            
            # Wait for form to load
            self.wait.until(EC.presence_of_element_located((By.ID, "reg_no")))
            
            # Enter Registration Number
            reg_input = self.driver.find_element(By.ID, "reg_no")
            reg_input.clear()
            reg_input.send_keys(registration_no)
            
            # Select Program
            program_dropdown = Select(self.driver.find_element(By.ID, "pro_id"))
            program_dropdown.select_by_value(program_id)
            time.sleep(2)  # Wait for exam dropdown to populate via AJAX
            
            # Select Session
            session_dropdown = Select(self.driver.find_element(By.ID, "sess_id"))
            session_dropdown.select_by_value(session_id)
            
            # Select Exam
            self.wait.until(EC.presence_of_element_located((By.ID, "exam_id")))
            exam_dropdown = Select(self.driver.find_element(By.ID, "exam_id"))
            
            if exam_id:
                exam_dropdown.select_by_value(exam_id)
            else:
                # Select first available exam
                if len(exam_dropdown.options) > 0:
                    exam_dropdown.select_by_index(0)
            
            # Submit form
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            submit_btn.click()
            
            # Wait for results to load in the exam_result div
            time.sleep(4)
            
            return True
            
        except Exception as e:
            print(f"Error filling form: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    def fetch_available_exams(self, program_id: str = "14", session_id: str = "23") -> List[Dict]:
        """
        Fetch all available exams from the dropdown for a program and session
        
        Args:
            program_id: Program ID (default: "14" for B.Sc. in CSE)
            session_id: Session ID (default: "23" for 2022-2023)
            
        Returns:
            List of dictionaries containing exam 'id' and 'name'
        """
        try:
            self.driver.get(self.url)
            time.sleep(2)
            
            # Wait for form to load
            self.wait.until(EC.presence_of_element_located((By.ID, "reg_no")))
            
            # Select Program
            program_dropdown = Select(self.driver.find_element(By.ID, "pro_id"))
            program_dropdown.select_by_value(program_id)
            time.sleep(2)  # Wait for exam dropdown to populate via AJAX
            
            # Select Session
            session_dropdown = Select(self.driver.find_element(By.ID, "sess_id"))
            session_dropdown.select_by_value(session_id)
            time.sleep(2)  # Wait for exam dropdown to populate
            
            # Read Exam dropdown options
            self.wait.until(EC.presence_of_element_located((By.ID, "exam_id")))
            exam_dropdown = Select(self.driver.find_element(By.ID, "exam_id"))
            
            exams = []
            for option in exam_dropdown.options:
                val = option.get_attribute('value')
                text = option.text.strip()
                if val and text and "Select" not in text:
                    exams.append({
                        'id': val,
                        'name': text
                    })
            return exams
            
        except Exception as e:
            print(f"Error fetching available exams: {e}")
            return []
     
    def extract_result_data(self) -> Dict:
        """Extract student information and grades from the result page"""
        try:
            result_data = {
                'student_info': {},
                'subjects': [],
                'status': ''
            }
            
            # Check if result is available
            try:
                output_div = self.driver.find_element(By.ID, "outputspass")
                error_msg = output_div.text.strip()
                if error_msg:
                    result_data['error'] = error_msg
                    return result_data
            except NoSuchElementException:
                pass
            
            # Extract student information
            # Wait for the exam_result div to be populated
            self.wait.until(EC.presence_of_element_located((By.ID, "exam_result")))
            time.sleep(2)  # Additional wait for content to render
            
            info_table = self.driver.find_element(By.XPATH, "//div[@id='exam_result']//table[@class='table table-bordered']")
            rows = info_table.find_elements(By.TAG_NAME, "tr")
            
            for row in rows:  # Process all rows
                cells = row.find_elements(By.TAG_NAME, "th") + row.find_elements(By.TAG_NAME, "td")
                if len(cells) >= 2:
                    key = cells[0].text.strip()
                    value = cells[1].text.strip()
                    if key:  # Only add non-empty keys
                        result_data['student_info'][key] = value
            
            # Extract subject grades
            subject_table = self.driver.find_element(By.XPATH, "//table[@width='100%'][@border='1']")
            subject_rows = subject_table.find_elements(By.TAG_NAME, "tr")[1:]  # Skip header
            
            for row in subject_rows:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) >= 5:
                    grade = cells[3].text.strip()
                    point_str = cells[4].text.strip()
                    
                    # Ensure failed subjects have 0.0 point
                    if grade.upper() == 'F' or point_str.upper() == 'F' or 'FAIL' in grade.upper():
                        point_str = '0.0'
                    
                    subject = {
                        'sl': cells[0].text.strip(),
                        'code': cells[1].text.strip(),
                        'title': cells[2].text.strip(),  # Using 'title' instead of 'name' for consistency
                        'grade': grade,
                        'point': point_str,
                        'status': 'FAIL' if grade.upper() == 'F' or 'FAIL' in grade.upper() else 'PASS'
                    }
                    result_data['subjects'].append(subject)
            
            # Extract status (Promoted/Failed)
            try:
                status_div = self.driver.find_element(By.XPATH, "//div[@style='text-align: center;font-weight: bold;font-size: 25px;']")
                result_data['status'] = status_div.text.strip()
            except NoSuchElementException:
                result_data['status'] = 'Unknown'
            
            return result_data
            
        except Exception as e:
            print(f"Error extracting result data: {e}")
            return {'error': str(e)}
    
    def calculate_gpa(self, subjects: List[Dict], formula: str = "custom") -> float:
        """
        Calculate GPA based on the provided formula
        
        Args:
            subjects: List of subject dictionaries with grades and points
            formula: Calculation method - "average", "weighted", or "custom"
        
        Returns:
            Calculated GPA
        """
        try:
            # Extract grade points
            points = []
            for subject in subjects:
                try:
                    point = float(subject['point'])
                    points.append(point)
                except (ValueError, KeyError):
                    continue
            
            if not points:
                return 0.0
            
            if formula == "custom":
                # Use actual course credits from COURSES_DATA
                total_weighted = 0.0
                total_credits = 0.0
                
                for subject in subjects:
                    try:
                        code = subject.get('code', '').strip()
                        grade = subject.get('grade', '').strip()
                        point_str = subject.get('point', '0').strip()
                        
                        # Handle failed subjects - if grade is 'F' or point is 'F', set point to 0
                        if grade.upper() == 'F' or point_str.upper() == 'F' or 'FAIL' in grade.upper():
                            point = 0.0
                        else:
                            try:
                                point = float(point_str)
                            except (ValueError, TypeError):
                                point = 0.0
                        
                        # Get credit from COURSES_DATA, fallback to positional credits
                        if code in COURSES_DATA:
                            credit = COURSES_DATA[code]
                        else:
                            # Fallback: Use old positional logic if course code not found
                            idx = subjects.index(subject)
                            if idx < 5:
                                credit = 3.0
                            elif idx == 5:
                                credit = 2.0
                            elif idx < 9:
                                credit = 1.5
                            else:
                                credit = 0.75
                        
                        total_weighted += credit * point
                        total_credits += credit
                        
                    except (ValueError, KeyError):
                        continue
                
                if total_credits == 0:
                    return 0.0
                
                gpa = total_weighted / total_credits
                
            elif formula == "average":
                # Simple average of all grade points
                gpa = sum(points) / len(points)
                
            elif formula == "weighted":
                # Generic weighted average (can be customized)
                gpa = sum(points) / len(points)
            else:
                # Default to custom formula
                gpa = sum(points) / len(points)
            
            return round(gpa, 2)
            
        except Exception as e:
            print(f"Error calculating GPA: {e}")
            return 0.0
    
    def get_result(self, registration_no: str, program_id: str = "14", 
                   exam_id: str = "1563", session_id: str = "23", gpa_formula: str = "custom") -> Dict:
        """
        Complete workflow: Fill form, extract data, and calculate GPA
        
        Args:
            registration_no: Student registration number
            program_id: Program ID (default: "14" for B.Sc. in Computer Science and Engineering)
            exam_id: Exam ID (default: "1563" for 2nd year 1st Semester 2024)
            session_id: Session ID (default: "23" for 2022-2023)
            cgpa_formula: Formula for CGPA calculation
        
        Returns:
            Dictionary containing all result data and calculated GPA
        """
        # Fill the form
        if not self.fill_form(registration_no, program_id, exam_id, session_id):
            return {'error': 'Failed to fill form'}
        
        # Extract result data
        result_data = self.extract_result_data()
        
        # Check for errors
        if 'error' in result_data:
            return result_data
        
        # Calculate GPA
        if result_data.get('subjects'):
            gpa = self.calculate_gpa(result_data['subjects'], gpa_formula)
            result_data['calculated_gpa'] = gpa
        
        return result_data
    
    def process_multiple_registrations(self, registration_numbers: List[str], 
                                      program_id: str = "14", 
                                      exam_id: str = "1563",
                                      session_id: str = "23",
                                      cgpa_formula: str = "custom",
                                      min_delay: int = 3,
                                      max_delay: int = 7) -> List[Dict]:
        """
        Process multiple registration numbers
        
        Args:
            registration_numbers: List of registration numbers
            program_id: Program ID
            exam_id: Exam ID
            session_id: Session ID
            cgpa_formula: Formula for CGPA calculation
            min_delay: Minimum delay between requests in seconds
            max_delay: Maximum delay between requests in seconds
        
        Returns:
            List of result dictionaries
        """
        import random
        
        results = []
        
        for idx, reg_no in enumerate(registration_numbers):
            print(f"\nProcessing registration: {reg_no}")
            result = self.get_result(reg_no, program_id, exam_id, session_id, cgpa_formula)
            results.append({
                'registration': reg_no,
                'data': result
            })
            
            # Random delay between requests to avoid IP blocking
            # Skip delay after the last request
            if idx < len(registration_numbers) - 1:
                delay = random.uniform(min_delay, max_delay)
                print(f"⏳ Waiting {delay:.1f} seconds before next request...")
                time.sleep(delay)
        
        return results
    
    def close(self):
        """Close the browser"""
        self.driver.quit()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def print_result(result_data: Dict, output_file: str = None, registration_no: str = None):
    """Print formatted result data and optionally save to file"""
    output_lines = []
    
    if 'error' in result_data:
        error_msg = f"Registration: {registration_no} - Error: {result_data['error']}"
        print(error_msg)
        if output_file:
            output_lines.append(error_msg)
        return
    
    # Get student name and exam roll from student_info
    student_info = result_data.get('student_info', {})
    student_name = (student_info.get("Student's Name") or 
                    student_info.get("Name") or 
                    student_info.get("name") or 
                    student_info.get("student_name") or 
                    'N/A')
    exam_roll = student_info.get('Exam Roll', 'N/A')
    
    # Simple output: Registration, Exam Roll, Name, and CGPA
    if 'calculated_cgpa' in result_data:
        cgpa = result_data['calculated_cgpa']
        line = f"Registration: {registration_no} - Exam Roll: {exam_roll} - Name: {student_name} - CGPA: {cgpa}"
        output_lines.append(line)
        print(line)
    else:
        line = f"Registration: {registration_no} - Exam Roll: {exam_roll} - Name: {student_name} - CGPA: N/A"
        output_lines.append(line)
        print(line)
    
    # Save to file if specified
    if output_file:
        try:
            with open(output_file, 'a', encoding='utf-8') as f:
                f.write('\n'.join(output_lines) + '\n')
        except Exception as e:
            print(f"❌ Error saving to file: {e}")


def generate_pdf_report(results: List[Dict], pdf_filename: str = "results_sorted.pdf"):
    """Generate a PDF report with results in table format"""
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font('Arial', 'B', 16)
        
        # Title
        pdf.cell(0, 10, 'DUCMC Result Report - Sorted by CGPA', 0, 1, 'C')
        pdf.ln(5)
        
        # Table header
        pdf.set_font('Arial', 'B', 10)
        pdf.set_fill_color(47, 27, 114)  # DUCMC purple color
        pdf.set_text_color(255, 255, 255)  # White text
        
        # Column widths
        col_widths = [15, 35, 25, 95, 20]
        
        pdf.cell(col_widths[0], 10, 'No.', 1, 0, 'C', True)
        pdf.cell(col_widths[1], 10, 'Registration', 1, 0, 'C', True)
        pdf.cell(col_widths[2], 10, 'Exam Roll', 1, 0, 'C', True)
        pdf.cell(col_widths[3], 10, 'Student Name', 1, 0, 'C', True)
        pdf.cell(col_widths[4], 10, 'CGPA', 1, 1, 'C', True)
        
        # Table data
        pdf.set_font('Arial', '', 9)
        pdf.set_text_color(0, 0, 0)  # Black text
        
        for idx, item in enumerate(results, 1):
            result_data = item['data']
            registration_no = item['registration']
            
            if 'error' in result_data:
                continue
            
            student_info = result_data.get('student_info', {})
            student_name = (student_info.get("Student's Name") or 
                            student_info.get("Name") or 
                            'N/A')
            exam_roll = student_info.get('Exam Roll', 'N/A')
            cgpa = result_data.get('calculated_cgpa', 'N/A')
            
            # Alternate row colors
            if idx % 2 == 0:
                pdf.set_fill_color(240, 240, 240)
            else:
                pdf.set_fill_color(255, 255, 255)
            
            pdf.cell(col_widths[0], 8, str(idx), 1, 0, 'C', True)
            pdf.cell(col_widths[1], 8, registration_no, 1, 0, 'C', True)
            pdf.cell(col_widths[2], 8, str(exam_roll), 1, 0, 'C', True)
            pdf.cell(col_widths[3], 8, student_name[:45], 1, 0, 'L', True)  # Truncate long names
            pdf.cell(col_widths[4], 8, str(cgpa), 1, 1, 'C', True)
        
        # Footer
        pdf.ln(5)
        pdf.set_font('Arial', 'I', 8)
        pdf.cell(0, 10, f'Total Students: {len(results)}', 0, 1, 'L')
        
        pdf.output(pdf_filename)
        print(f"\n📄 PDF report generated: {pdf_filename}")
        return True
    except Exception as e:
        print(f"\n❌ Error generating PDF: {e}")
        return False


# Example usage
if __name__ == "__main__":
    # Program and exam IDs - find these by inspecting the dropdown values on the website
    PROGRAM_ID = "14"  # B.Sc. in Computer Science and Engineering
    EXAM_ID = "1563"   # B.Sc. in CSE 2nd year 1st Semester Examination of 2024
    SESSION_ID = "23"  # 2022-2023
    
    # You can customize the CGPA calculation formula here
    # Options: "average", "weighted", or "custom"
    # "custom" uses the specific credit-weighted formula:
    # (3.0 * GPA for first 5 subjects) + (2.0 * GPA for 6th) + 
    # (1.5 * GPA for subjects 7-9) + (0.75 * GPA for 10th) / 22.25
    CGPA_FORMULA = "custom"
    
    print("DU Crack - Batch Processing")
    print("="*70)
    
    # Read registration numbers from sample_registrations.txt
    registration_list = []
    try:
        with open('sample_registrations.txt', 'r') as f:
            registration_list = [line.strip() for line in f if line.strip()]
        print(f"📋 Loaded {len(registration_list)} registration numbers from sample_registrations.txt")
    except FileNotFoundError:
        print("❌ Error: sample_registrations.txt not found!")
        exit(1)
    
    if not registration_list:
        print("❌ Error: No registration numbers found in sample_registrations.txt")
        exit(1)
    
    # Fixed output filenames
    output_file_batch = "results_sorted.txt"
    pdf_filename = "results_sorted.pdf"
    
    # Clear previous results file if it exists
    try:
        with open(output_file_batch, 'w', encoding='utf-8') as f:
            f.write('')
    except:
        pass
    
    # Using context manager for automatic cleanup
    with DUCMCResultScraper(headless=False) as scraper:
        # Process multiple registrations
        results = scraper.process_multiple_registrations(
            registration_numbers=registration_list,
            program_id=PROGRAM_ID,
            exam_id=EXAM_ID,
            session_id=SESSION_ID,
            cgpa_formula=CGPA_FORMULA,
            min_delay=3,  # Minimum 3 seconds between requests
            max_delay=7   # Maximum 7 seconds between requests
        )
        
        # Sort results by CGPA (descending order)
        sorted_results = sorted(
            results,
            key=lambda x: x['data'].get('calculated_cgpa', 0.0),
            reverse=True
        )
        
        # Print and save sorted results
        print("\n" + "="*70)
        print("RESULTS SORTED BY CGPA (Highest to Lowest)")
        print("="*70)
        for item in sorted_results:
            print_result(item['data'], output_file_batch, item['registration'])
    
    # Generate PDF report
    generate_pdf_report(sorted_results, pdf_filename)
    
    print("\n✅ Batch scraping completed!")
    print(f"📁 Results saved to: {output_file_batch}")
    print(f"📄 PDF report saved to: {pdf_filename}")