courses_data={"Semester 1":[{"code":"CSE-1101","title":"Fundamentals of Computers and Computing","credit":2.0},{"code":"CSE-1102","title":"Discrete Mathematics","credit":3.0},{"code":"EEE-1103","title":"Electrical Circuits","credit":3.0},{"code":"CHE-1104","title":"Chemistry","credit":3.0},{"code":"MATH-1105","title":"Differential and Integral Calculus","credit":3.0},{"code":"SS-1106","title":"Government and Public Administration","credit":2.0},{"code":"CSE-1111","title":"Fundamentals of Computers and Computing Lab","credit":1.5},{"code":"EEE-1113","title":"Electrical Circuits Lab","credit":1.5},{"code":"CHE-1114","title":"Chemistry Lab","credit":1.5}],"Semester 2":[{"code":"CSE-1201","title":"Fundamentals of Programming","credit":3.0},{"code":"CSE-1202","title":"Digital Logic Design","credit":3.0},{"code":"PHY-1203","title":"Physics","credit":3.0},{"code":"MATH-1204","title":"Methods of Integration, Differential Equations and Series","credit":3.0},{"code":"ENG-1205","title":"Developing English Language Skills","credit":2.0},{"code":"CSE-1211","title":"Fundamentals of Programming Lab","credit":3.0},{"code":"CSE-1212","title":"Digital Logic Design Lab","credit":1.5},{"code":"PHY-1213","title":"Physics Lab","credit":1.5},{"code":"ENG-1215","title":"Developing English Language Skills Lab","credit":1.5}],"Semester 3":[{"code":"CSE-2101","title":"Data Structures and Algorithms","credit":3.0},{"code":"CSE-2102","title":"Object Oriented Programming","credit":3.0},{"code":"CSE-2103","title":"Digital Electronics and Pulse Technique","credit":3.0},{"code":"EEE-2104","title":"Electronic Devices and Circuits","credit":3.0},{"code":"MATH-2105","title":"Linear Algebra","credit":3.0},{"code":"SS-2106","title":"Bangladesh Studies","credit":2.0},{"code":"CSE-2111","title":"Data Structures and Algorithms Lab","credit":1.5},{"code":"CSE-2112","title":"Object Oriented Programming Lab","credit":1.5},{"code":"CSE-2113","title":"Digital Electronics and Pulse Technique Lab","credit":1.5},{"code":"EEE-2114","title":"Electronic Devices and Circuits Lab","credit":0.75}],"Semester 4":[{"code":"CSE-2201","title":"Database Management Systems-I","credit":3.0},{"code":"CSE-2202","title":"Design and Analysis of Algorithms-I","credit":3.0},{"code":"CSE-2203","title":"Data and Telecommunication","credit":3.0},{"code":"CSE-2204","title":"Computer Architecture and Organization","credit":3.0},{"code":"CSE-2205","title":"Introduction to Mechatronics","credit":2.0},{"code":"CSE-2211","title":"Database Management Systems - I Lab","credit":1.5},{"code":"CSE-2212","title":"Design and Analysis of Algorithms - I Lab","credit":1.5},{"code":"CSE-2213","title":"Data and Telecommunication Lab","credit":0.75},{"code":"CSE-2216","title":"Application Development Lab","credit":1.5}],"Semester 5":[{"code":"CSE-3101","title":"Computer Networking","credit":3.0},{"code":"CSE-3102","title":"Software Engineering","credit":3.0},{"code":"CSE-3103","title":"Microprocessor and Microcontroller","credit":3.0},{"code":"CSE-3104","title":"Database Management Systems -II","credit":3.0},{"code":"MATH-3105","title":"Multivariable Calculus and Geometry","credit":3.0},{"code":"CSE-3111","title":"Computer Networking Lab","credit":1.5},{"code":"CSE-3112","title":"Software Engineering Lab","credit":0.75},{"code":"CSE-3113","title":"Microprocessor and Assembly Language Lab","credit":1.5},{"code":"CSE-3116","title":"Microcontroller Lab","credit":0.75}],"Semester 6":[{"code":"CSE-3201","title":"Operating Systems","credit":3.0},{"code":"CSE-3202","title":"Numerical Methods","credit":3.0},{"code":"CSE-3203","title":"Design and Analysis of Algorithms - II","credit":3.0},{"code":"CSE-3204","title":"Formal Language, Automata and Computability","credit":3.0},{"code":"STAT-3205","title":"Introduction to Probability and Statistics","credit":3.0},{"code":"CSE-3211","title":"Operating Systems Lab","credit":1.5},{"code":"CSE-3212","title":"Numerical Methods Lab","credit":0.75},{"code":"CSE-3216","title":"Software Design Patterns Lab","credit":1.5},{"code":"ENG-3217","title":"Technical Writing and Presentation Lab","credit":0.75}],"Semester 7":[{"code":"CSE-4101","title":"Artificial Intelligence","credit":3.0},{"code":"CSE-4102","title":"Mathematical and Statistical Analysis for Engineers","credit":3.0},{"code":"SS-4103","title":"Entrepreneurship for IT Business","credit":2.0},{"code":"CSE-4XXX","title":"Option-I","credit":3.0},{"code":"CSE-4XXX","title":"Option-II","credit":3.0},{"code":"CSE-4111","title":"Artificial Intelligence Lab","credit":1.5},{"code":"CSE-4XXX","title":"Option-I Lab","credit":1.5},{"code":"CSE-4113","title":"Internet Programming Lab","credit":1.5},{"code":"CSE-4114","title":"Project","credit":2.0}],"Semester 8":[{"code":"ECO-4201","title":"Economics","credit":2.0},{"code":"CSE-4202","title":"Society and Technology","credit":2.0},{"code":"SS-4203","title":"Engineering Ethics","credit":2.0},{"code":"CSE-4XXX","title":"Option-III","credit":3.0},{"code":"CSE-4XXX","title":"Option-IV","credit":3.0},{"code":"CSE-4XXX","title":"Option-III Lab","credit":1.5},{"code":"CSE-4214","title":"Project","credit":4.0}]}

# Canonical flat code→credit map derived from courses_data (single source of truth).
# Used by services.py and scraper_worker.py for consistent GPA storage.
COURSES_DATA={course["code"]:course["credit"] for sem in courses_data.values() for course in sem if course["code"]!="CSE-4XXX"}
_NORMALIZED_COURSES = {code.replace(' ', '').replace('-', '').upper(): credit for code, credit in COURSES_DATA.items()}


def calculate_semester_gpa(semester_name,grades):
 courses=courses_data.get(semester_name, [])
 total_grade_points=total_credits=0
 for course in courses:
  course_code,credit=course["code"],course["credit"]
  if course_code in grades:
   total_grade_points+=grades[course_code]*credit
   total_credits+=credit
 return round(total_grade_points/total_credits,2)if total_credits>0 else 0.0


from app.utils.utils import positional_credit_fallback

def calculate_gpa(subjects):
 """Credit-weighted GPA calculation using the canonical COURSES_DATA.
 Uses course codes (unique per semester) for accurate credit lookup.
 This is the authoritative function used when storing GPA to the database."""
 total_weighted=0.0
 total_credits=0.0
 for idx,subject in enumerate(subjects):
  code=subject.get('code','').strip()
  norm_code = code.replace(' ', '').replace('-', '').upper()
  grade=subject.get('grade','').strip().upper()
  point_str=subject.get('point','0')
  if grade=='F' or 'FAIL' in grade:
   point=0.0
  else:
   try:point=float(point_str)
   except(ValueError,TypeError):point=0.0
  credit=_NORMALIZED_COURSES.get(norm_code)
  if credit is None:
   credit=positional_credit_fallback(idx)
  total_weighted+=credit*point
  total_credits+=credit
 return round(total_weighted/total_credits,2)if total_credits>0 else 0.0

