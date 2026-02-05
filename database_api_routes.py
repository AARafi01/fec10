# Add this route to your app.py for database stats

@app.route('/api/database/stats')
def database_stats():
    """API endpoint to get database statistics"""
    try:
        with db.get_connection() as conn:
            # Get basic counts
            exam_count = conn.execute("SELECT COUNT(*) FROM exams").fetchone()[0]
            result_count = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
            student_count = conn.execute("SELECT COUNT(DISTINCT registration_no) FROM results").fetchone()[0]
            
            # Get GPA statistics
            gpa_stats = conn.execute("""
                SELECT 
                    AVG(gpa) as avg_gpa,
                    MAX(gpa) as max_gpa,
                    MIN(gpa) as min_gpa,
                    COUNT(gpa) as total_with_gpa
                FROM results WHERE gpa IS NOT NULL
            """).fetchone()
            
            # Get exam breakdown
            exam_breakdown = conn.execute("""
                SELECT e.exam_name, e.exam_id, COUNT(r.id) as result_count
                FROM exams e 
                LEFT JOIN results r ON e.exam_id = r.exam_id 
                GROUP BY e.exam_id 
                ORDER BY result_count DESC
            """).fetchall()
            
            return jsonify({
                'success': True,
                'stats': {
                    'exams': exam_count,
                    'results': result_count,
                    'students': student_count,
                    'gpa_stats': dict(gpa_stats) if gpa_stats else {},
                    'exam_breakdown': [dict(row) for row in exam_breakdown]
                }
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Add this route for database backup
@app.route('/api/database/backup')
@login_required
def backup_database():
    """Create a backup of the database"""
    import shutil
    from datetime import datetime
    
    try:
        backup_name = f"database_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2('database.db', backup_name)
        return jsonify({'success': True, 'backup_file': backup_name})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})