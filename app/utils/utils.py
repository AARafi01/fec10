import re
from typing import Optional

def parse_semester_from_name(exam_name: str) -> Optional[int]:
    """
    Intelligently infer the semester number (1-8) from the exam's printed text
    """
    name_lower = exam_name.lower()
    
    # 1st Year
    if "1st year" in name_lower or "1st-year" in name_lower:
        if "1st semester" in name_lower or "1st-semester" in name_lower:
            return 1
        if "2nd semester" in name_lower or "2nd-semester" in name_lower:
            return 2
            
    # 2nd Year
    elif "2nd year" in name_lower or "2nd-year" in name_lower:
        if "1st semester" in name_lower or "1st-semester" in name_lower:
            return 3
        if "2nd semester" in name_lower or "2nd-semester" in name_lower:
            return 4
            
    # 3rd Year
    elif "3rd year" in name_lower or "3rd-year" in name_lower:
        if "1st semester" in name_lower or "1st-semester" in name_lower:
            return 5
        if "2nd semester" in name_lower or "2nd-semester" in name_lower:
            return 6
            
    # 4th Year
    elif "4th year" in name_lower or "4th-year" in name_lower:
        if "1st semester" in name_lower or "1st-semester" in name_lower:
            return 7
        if "2nd semester" in name_lower or "2nd-semester" in name_lower:
            return 8
            
    # Default fallback
    return None

def is_retake_improvement(exam_name: str) -> bool:
    name_lower = exam_name.lower()
    return "retake" in name_lower or "improvement" in name_lower or "retake/improvement" in name_lower or "retake/impovement" in name_lower

def standardize_exam_name(exam_name: str) -> str:
    name_lower = exam_name.lower()
    year_match = re.search(r'([1-4])(?:st|nd|rd|th)?\s+year', name_lower)
    sem_match = re.search(r'([1-2])(?:st|nd|rd|th)?\s+semester', name_lower)
    if year_match and sem_match:
        year = int(year_match.group(1))
        sem = int(sem_match.group(1))
        
        year_suffixes = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
        sem_suffixes = {1: "1st", 2: "2nd"}
        
        is_retake = is_retake_improvement(exam_name)
        
        standardized_base = f"{year_suffixes[year]} Year {sem_suffixes[sem]} Semester"
        if is_retake:
            return f"{standardized_base} - Retake/Improvement"
        return standardized_base
    return exam_name

def positional_credit_fallback(idx: int) -> float:
    if idx < 5:
        return 3.0
    elif idx == 5:
        return 2.0
    elif idx < 9:
        return 1.5
    else:
        return 0.75
