let currentResults = [];
let currentSortBy = 'gpa'; // Default sort by GPA

document.getElementById('examForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const examId = document.getElementById('exam_id').value;

    if (!examId) {
        showToast('Please select an exam', 'warning');
        return;
    }

    // Show loading
    document.getElementById('loading').style.display = 'block';
    document.getElementById('resultsContainer').style.display = 'none';

    try {
        const formData = new FormData();
        formData.append('exam_id', examId);

        const response = await fetch('/process_results', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (data.error) {
            showToast(data.error || 'Failed to process results', 'error');
            return;
        }

        // Display results
        displayResults(data.results, examId);

    } catch (error) {
        showToast('Error processing results: ' + error.message, 'error');
        console.error(error);
    } finally {
        setTimeout(() => {
            document.getElementById('loading').style.display = 'none';
        }, 300);
    }
});

function displayResults(results, examId) {
    currentResults = results; // Store results globally for sorting
    const examSelect = document.getElementById('exam_id');
    const optionText = examSelect.options[examSelect.selectedIndex].text;
    const examTitle = optionText.split(' (Exam Year:')[0].trim();
    document.getElementById('examTitle').textContent = examTitle;

    // Reset search input
    document.getElementById('searchInput').value = '';

    // Sort by default (GPA) and render
    sortTable('gpa');
    document.getElementById('resultsContainer').style.display = 'block';
}

function renderTable(results) {
    const tbody = document.getElementById('resultsBody');
    let html = '';

    results.forEach((result, index) => {
        const gpaValue = result.gpa || 0;
        const cgpaValue = result.cgpa || 0;
        const gpaClass = window.DUCrackResults.getGpaClass(gpaValue);
        const cgpaClass = window.DUCrackResults.getGpaClass(cgpaValue);
        const subjectsJson = result.subjects ? JSON.stringify(result.subjects).replace(/'/g, "&#39;") : 'null';

        html += `
            <tr>
                <td class="serial-col">${index + 1}</td>
                <td>${result.registration}</td>
                <td><strong>${result.class_roll || 'N/A'}</strong></td>
                <td>${result.name || result.error || 'N/A'}</td>
                <td><span class="gpa-badge ${gpaClass}">${gpaValue.toFixed(2)}</span></td>
                <td><span class="gpa-badge ${cgpaClass}">${cgpaValue.toFixed(2)}</span></td>
                <td>
                    ${result.subjects ? `
                        <button class="btn btn-sm btn-info" onclick='showSubjects(${subjectsJson})'>
                            <i class="fas fa-eye"></i> View Subjects
                        </button>
                    ` : '<span class="text-muted">N/A</span>'}
                </td>
            </tr>
        `;
    });
    
    tbody.innerHTML = html;
}

function filterAndRender() {
    const query = document.getElementById('searchInput').value.toLowerCase().trim();
    let filtered = [...currentResults];

    if (query) {
        filtered = filtered.filter(row => 
            (row.registration && row.registration.toLowerCase().includes(query)) ||
            (row.class_roll && row.class_roll.toLowerCase().includes(query)) ||
            (row.name && row.name.toLowerCase().includes(query))
        );
    }

    // Sort
    filtered.sort((a, b) => {
        if (currentSortBy === 'registration') {
            const aValue = (a[currentSortBy] || '').toString();
            const bValue = (b[currentSortBy] || '').toString();
            const aLastThree = parseInt(aValue.slice(-3)) || 0;
            const bLastThree = parseInt(bValue.slice(-3)) || 0;
            return aLastThree - bLastThree;
        } else if (currentSortBy === 'class_roll') {
            const aValue = parseInt((a[currentSortBy] || '').toString().replace(/[^0-9]/g, '')) || 0;
            const bValue = parseInt((b[currentSortBy] || '').toString().replace(/[^0-9]/g, '')) || 0;
            return aValue - bValue;
        } else {
            const aValue = parseFloat(a[currentSortBy]) || 0;
            const bValue = parseFloat(b[currentSortBy]) || 0;
            return bValue - aValue;
        }
    });

    renderTable(filtered);
}

function sortTable(sortBy) {
    currentSortBy = sortBy;

    // Update active sort title text
    const sortTextEl = document.getElementById('activeSortText');
    if (sortTextEl) {
        if (sortBy === 'gpa') {
            sortTextEl.textContent = 'GPA Sorted';
        } else if (sortBy === 'cgpa') {
            sortTextEl.textContent = 'CGPA Sorted';
        } else if (sortBy === 'registration') {
            sortTextEl.textContent = 'Reg No Sorted';
        } else if (sortBy === 'class_roll') {
            sortTextEl.textContent = 'Class Roll Sorted';
        }
    }

    // Update sort indicators
    const gpaSort = document.getElementById('gpaSort');
    const cgpaSort = document.getElementById('cgpaSort');
    const registrationSort = document.getElementById('registrationSort');
    const classRollSort = document.getElementById('class_rollSort');

    // Reset all indicators to show inactive sort icons
    gpaSort.innerHTML = '<i class="fas fa-sort text-muted opacity-50 sort-icon"></i>';
    cgpaSort.innerHTML = '<i class="fas fa-sort text-muted opacity-50 sort-icon"></i>';
    registrationSort.innerHTML = '<i class="fas fa-sort text-muted opacity-50 sort-icon"></i>';
    classRollSort.innerHTML = '<i class="fas fa-sort text-muted opacity-50 sort-icon"></i>';

    // Set active indicator checkmark
    if (sortBy === 'gpa') {
        gpaSort.innerHTML = '✓';
    } else if (sortBy === 'cgpa') {
        cgpaSort.innerHTML = '✓';
    } else if (sortBy === 'registration') {
        registrationSort.innerHTML = '✓';
    } else if (sortBy === 'class_roll') {
        classRollSort.innerHTML = '✓';
    }

    filterAndRender();
}

// Debounce utility
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

const debouncedFilterAndRender = debounce(filterAndRender, 300);

// Attach search input listener
document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', debouncedFilterAndRender);
    }
});

function showSubjects(subjects) {
    const detailsDiv = document.getElementById('subjectDetails');

    let html = '<table class="table table-striped"><thead><tr><th>SL</th><th>Code</th><th>Grade</th><th>Point</th></tr></thead><tbody>';

    subjects.forEach(subject => {
        const rowClass = subject.improved ? 'class="improved-row"' : '';
        const badge = subject.improved ? '<span class="badge badge-improved ms-2">Improved</span>' : '';
        html += `
                <tr ${rowClass}>
                    <td>${subject.sl}</td>
                    <td>${subject.code}</td>
                    <td><strong>${subject.grade}</strong>${badge}</td>
                    <td>${subject.point}</td>
                </tr>
            `;
    });

    html += '</tbody></table>';
    detailsDiv.innerHTML = html;

    const modal = new bootstrap.Modal(document.getElementById('subjectModal'));
    modal.show();
}
