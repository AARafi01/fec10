import sqlite3
import json

conn = sqlite3.connect('database.db')
cursor = conn.execute('SELECT exam_id, registration_no, result_data FROM results WHERE registration_no = "2022-154-842" LIMIT 1')
result = cursor.fetchone()

if result and result[2]:
    print(f"Exam ID: {result[0]}")
    print(f"Registration: {result[1]}")
    print("\nResult data structure:")
    data = json.loads(result[2])
    print(json.dumps(data, indent=2))
    
    print("\nSubjects structure:")
    if 'subjects' in data:
        for i, subject in enumerate(data['subjects']):
            print(f"Subject {i}: {subject}")
            
conn.close()