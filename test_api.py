import requests
import json

try:
    response = requests.get('http://localhost:5000/api/student_grades/2022-154-842')
    data = response.json()
    print("API Response:")
    print(json.dumps(data, indent=2))
except Exception as e:
    print(f"Error: {e}")