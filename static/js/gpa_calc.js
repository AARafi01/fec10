// Courses data, grade storage, and semester-exam mapping
const coursesData = {};
let currentRegistration = '';
let storedGrades = {}; // Will be loaded from localStorage

// Semester to exam mapping (update this mapping as needed)
const semesterExamMapping = {
    '1': '966',
    '2': '1221',
    '3': '1563',
    '4': '', // Add exam IDs as they are created
    '5': '',
    '6': '',
    '7': '',
    '8': ''
};

// Reverse mapping for finding semester from exam ID
const examSemesterMapping = {};
Object.keys(semesterExamMapping).forEach(sem => {
    if (semesterExamMapping[sem]) {
        examSemesterMapping[semesterExamMapping[sem]] = sem;
    }
});

// Initialize
document.addEventListener('DOMContentLoaded', function () {
    loadCoursesData();
    loadStoredGrades();
    setupEventListeners();
    // Auto-focus the registration input when the page loads
    document.getElementById('registration').focus();
});

function loadCoursesData() {
    fetch('/api/gpa_courses')
        .then(res => res.json())
        .then(data => {
            Object.assign(coursesData, data);
            populateSemesterDropdown();
        })
        .catch(err => console.error('Error loading courses:', err));
}

function populateSemesterDropdown() {
    const semesterSelect = document.getElementById('semester');
    semesterSelect.innerHTML = '';

    // Add semester options based on available courses data
    for (let i = 1; i <= 8; i++) {
        const semesterKey = `Semester ${i}`;

        if (coursesData[semesterKey]) {
            const option = document.createElement('option');
            option.value = i;
            option.textContent = `Semester ${i}`;
            semesterSelect.appendChild(option);
        }
    }

    // Auto-select and load the first available semester
    if (semesterSelect.options.length > 0) {
        semesterSelect.selectedIndex = 0;
        loadSemesterCourses(semesterSelect.value);
    }
}

function setupEventListeners() {
    // Registration input handler
    document.getElementById('registration').addEventListener('input', function () {
        const regNo = window.DUCrackCommon.formatRegistrationNumber(this.value);
        this.value = regNo;
        if (regNo !== currentRegistration) {
            currentRegistration = regNo;
            // Load stored grades for this registration
            loadStoredGrades();
        }
    });

    // Fetch grades button handler
    document.getElementById('fetchGradesBtn').addEventListener('click', fetchGradesFromServer);

    // Enter key on registration input triggers fetch
    document.getElementById('registration').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            fetchGradesFromServer();
        }
    });

    // Semester selection handler
    document.getElementById('semester').addEventListener('change', function () {
        const semester = this.value;
        loadSemesterCourses(semester);
    });
}

function loadStoredGrades() {
    if (!currentRegistration) {
        storedGrades = {};
        return;
    }

    const stored = localStorage.getItem(`grades_${currentRegistration}`);
    storedGrades = stored ? JSON.parse(stored) : {};
}

function saveStoredGrades() {
    if (currentRegistration) {
        // Clear any other stored grades to prevent localStorage bloat
        const keysToRemove = [];
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            if (key && key.startsWith('grades_') && key !== `grades_${currentRegistration}`) {
                keysToRemove.push(key);
            }
        }
        keysToRemove.forEach(key => localStorage.removeItem(key));
        
        localStorage.setItem(`grades_${currentRegistration}`, JSON.stringify(storedGrades));
    }
}

async function fetchGradesFromServer() {
    let regNo = window.DUCrackCommon.formatRegistrationNumber(document.getElementById('registration').value);
    document.getElementById('registration').value = regNo;
    if (!regNo) {
        showToast('Please enter a registration number');
        return;
    }

    const btn = document.getElementById('fetchGradesBtn');
    const originalContent = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';
    btn.disabled = true;

    try {
        const response = await fetch(`/api/student_grades/${encodeURIComponent(regNo)}`);
        const data = await response.json();

        if (data.success) {
            // Update registration field and currentRegistration with resolved value
            // Clear previous stored grades for a different registration
            if (currentRegistration && currentRegistration !== data.registration_no) {
                localStorage.removeItem(`grades_${currentRegistration}`);
            }
            document.getElementById('registration').value = data.registration_no;
            currentRegistration = data.registration_no;
            // Overwrite stored grades with server data
            storedGrades = {};

            // Process each semester's grades
            Object.keys(data.grades).forEach(examId => {
                const semester = examSemesterMapping[examId]; // Find semester number from exam ID
                if (semester && data.grades[examId]) {
                    storedGrades[semester] = {};
                    const fetchedGrades = data.grades[examId];

                    // Match grades by course code
                    const semesterKey = `Semester ${semester}`;
                    if (coursesData[semesterKey]) {
                        coursesData[semesterKey].forEach((course, index) => {
                            // Multiple matching strategies
                            let matchingGrade = null;

                            // Strategy 1: Exact course code match
                            matchingGrade = fetchedGrades.find(g => g.code === course.code);

                            // Strategy 2: Normalized course code match (remove spaces, dashes, case insensitive)
                            if (!matchingGrade) {
                                const normalizedCourseCode = course.code.replace(/[-\s]/g, '').toLowerCase();
                                matchingGrade = fetchedGrades.find(g =>
                                    g.code && g.code.replace(/[-\s]/g, '').toLowerCase() === normalizedCourseCode
                                );
                            }

                            // Strategy 3: Exact title match
                            if (!matchingGrade) {
                                matchingGrade = fetchedGrades.find(g =>
                                    g.title && course.title && g.title.toLowerCase() === course.title.toLowerCase()
                                );
                            }

                            // Strategy 4: Partial title match (keywords)
                            if (!matchingGrade) {
                                const courseKeywords = course.title.toLowerCase().split(/[\s,&()-]+/).filter(w => w.length > 3);
                                matchingGrade = fetchedGrades.find(g => {
                                    if (!g.title) return false;
                                    const gradeTitle = g.title.toLowerCase();
                                    return courseKeywords.some(keyword => gradeTitle.includes(keyword));
                                });
                            }

                            // Strategy 5: Subject code prefix match (CSE, MATH, PHY, etc.)
                            if (!matchingGrade) {
                                const subjectPrefix = course.code.split('-')[0];
                                matchingGrade = fetchedGrades.find(g => {
                                    if (!g.code) return false;
                                    const gradePrefix = g.code.split('-')[0];
                                    return gradePrefix === subjectPrefix && !fetchedGrades.some(used =>
                                        coursesData[semesterKey].slice(0, index).some(prevCourse =>
                                            used.code === g.code
                                        )
                                    );
                                });
                            }

                            if (matchingGrade) {
                                storedGrades[semester][index] = parseFloat(matchingGrade.grade || 0).toFixed(2);
                            } else {
                                storedGrades[semester][index] = '0.00';
                            }
                        });
                    }
                }
            });

            saveStoredGrades();

            // Reload current semester if selected
            const currentSemester = document.getElementById('semester').value;
            if (currentSemester) {
                loadSemesterCourses(currentSemester);
            }

            showToast(`Loaded grades for ${Object.keys(data.grades).length} semester(s)`);
        } else {
            showToast(data.message || 'Failed to load grades');
        }
    } catch (error) {
        console.error('Error fetching grades:', error);
        showToast('Error loading grades. Please try again.');
    } finally {
        btn.innerHTML = originalContent;
        btn.disabled = false;
    }
}

function loadSemesterCourses(semester) {
    const container = document.getElementById('coursesTableContainer');
    container.innerHTML = '';

    if (!semester) return;

    const semesterKey = `Semester ${semester}`;
    if (!coursesData[semesterKey]) {
        container.innerHTML = '<div class="alert alert-warning"><i class="fas fa-exclamation-triangle"></i> No courses found for this semester.</div>';
        return;
    }

    const courses = coursesData[semesterKey];
    let html = '<div class="table-responsive"><table class="table gpa-table"><thead><tr><th class="col-code">Course Code</th><th class="col-title">Course Title</th><th class="col-credit">Credits</th><th class="col-gpa">Grade Points</th></tr></thead><tbody>';

    courses.forEach((course, idx) => {
        // Get stored grade or default to 0
        let defaultGrade = '0.00';
        if (storedGrades[semester] && storedGrades[semester][idx] !== undefined) {
            defaultGrade = storedGrades[semester][idx];
        }

        html += `<tr>
                <td><input type="text" class="form-control readonly-input code-input" value="${course.code}" readonly tabindex="-1"></td>
                <td><input type="text" class="form-control readonly-input title-input" value="${course.title}" readonly tabindex="-1"></td>
                <td><input type="number" class="form-control readonly-input credit-input" value="${course.credit}" readonly tabindex="-1"></td>
                <td><input type="number" min="0" max="4" step="0.01" class="form-control gpa-input" data-semester="${semester}" data-idx="${idx}" value="${defaultGrade}" placeholder="Enter GPA"></td>
            </tr>`;
    });

    html += '</tbody></table></div>';
    container.innerHTML = html;

    // Add event listeners to GPA inputs
    document.querySelectorAll('.gpa-input').forEach(input => {
        input.addEventListener('input', function () {
            updateGPA();
            updateStoredGrade(this);
        });
    });

    // Calculate initial GPA
    updateGPA();
}

function updateStoredGrade(input) {
    const semester = input.dataset.semester;
    const idx = input.dataset.idx;
    const grade = parseFloat(input.value) || 0;

    if (!storedGrades[semester]) {
        storedGrades[semester] = {};
    }

    storedGrades[semester][idx] = grade.toFixed(2);
    saveStoredGrades();
}

function updateGPA() {
    const semester = document.getElementById('semester').value;
    if (!semester) return;

    const semesterKey = `Semester ${semester}`;

    if (!coursesData[semesterKey]) return;

    const courses = coursesData[semesterKey];
    let totalPoints = 0, totalCredits = 0;

    // Calculate semester GPA
    document.querySelectorAll('.gpa-input').forEach((input, idx) => {
        let gpa = parseFloat(input.value);
        if (isNaN(gpa)) gpa = 0.0;

        const credit = parseFloat(courses[idx].credit);
        totalPoints += gpa * credit;
        totalCredits += credit;
    });

    // Calculate semester GPA
    const semesterGPA = totalCredits ? (totalPoints / totalCredits) : 0.0;

    // Calculate CGPA as average of semester GPAs (non-zero positive semesters only)
    let semesterGPAs = [];

    // Include current semester GPA if it's positive
    if (semesterGPA > 0) {
        semesterGPAs.push(Number(semesterGPA.toFixed(2)));
    }

    // Calculate GPA for each stored semester that has grades (excluding current semester)
    Object.keys(storedGrades).forEach(sem => {
        // Skip current semester as we already included it above
        if (sem === semester) return;

        const semKey = `Semester ${sem}`;

        if (coursesData[semKey] && storedGrades[sem]) {
            let semesterPoints = 0, semesterCredits = 0;
            let hasNonZeroGrades = false;

            Object.keys(storedGrades[sem]).forEach(idx => {
                const grade = parseFloat(storedGrades[sem][idx]);
                const credit = parseFloat(coursesData[semKey][idx].credit);
                if (!isNaN(grade) && !isNaN(credit)) {
                    semesterPoints += grade * credit;
                    semesterCredits += credit;
                    if (grade > 0) hasNonZeroGrades = true;
                }
            });

            if (semesterCredits > 0 && hasNonZeroGrades) {
                const semGPA = semesterPoints / semesterCredits;
                if (semGPA > 0) { // Only include positive GPAs
                    semesterGPAs.push(Number(semGPA.toFixed(2)));
                }
            }
        }
    });

    // CGPA is the simple average of semester GPAs (sum of non-zero semesters / count of non-zero semesters)
    const cgpa = semesterGPAs.length > 0 ? (semesterGPAs.reduce((sum, gpa) => sum + gpa, 0) / semesterGPAs.length) : 0.0;

    // Display results
    document.getElementById('semesterGpaResult').innerHTML = `<i class="fas fa-calendar-alt"></i> Semester ${semester} GPA<br><strong>${semesterGPA.toFixed(2)}</strong>`;
    document.getElementById('cgpaResult').innerHTML = `<i class="fas fa-trophy"></i> CGPA<br><strong>${cgpa.toFixed(2)}</strong>`;
    document.getElementById('gpaResultContainer').style.display = 'block';
}
