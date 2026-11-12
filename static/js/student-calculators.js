(() => {
  const root = document.querySelector('.student-calculators');
  if (!root) return;

  const tabs = Array.from(root.querySelectorAll('[role="tab"]'));
  const panels = Array.from(root.querySelectorAll('[role="tabpanel"]'));
  const activateTab = (tab) => {
    tabs.forEach((item) => {
      const selected = item === tab;
      item.setAttribute('aria-selected', String(selected));
      item.tabIndex = selected ? 0 : -1;
    });
    panels.forEach((panel) => {
      const selected = panel.id === tab.getAttribute('aria-controls');
      panel.hidden = !selected;
      panel.classList.toggle('d-none', !selected);
    });
  };

  const initialTab = tabs.find((tab) =>
    tab.id.startsWith(root.dataset.activeCalculator || 'attendance')
  ) || tabs[0];
  if (initialTab) activateTab(initialTab);
  tabs.forEach((tab) => tab.addEventListener('click', () => activateTab(tab)));

  const attendanceSubjects = document.getElementById('attendance-subject-list');
  const addAttendanceSubject = document.getElementById('add-attendance-subject');
  const calculateOverallAttendance = document.getElementById('calculate-overall-attendance');
  const attendanceError = document.getElementById('attendance-subject-error');
  const attendanceResult = document.getElementById('overall-attendance-result');
  const subjectDetailsWrap = document.getElementById('subject-attendance-details-wrap');
  const subjectDetails = document.getElementById('subject-attendance-details');
  let attendanceSubjectNumber = 0;

  const addSubjectRow = () => {
    attendanceSubjectNumber += 1;
    const index = attendanceSubjectNumber;
    const row = document.createElement('div');
    row.className = 'calculator-course-row attendance-subject-row';
    row.innerHTML = `
      <div class="calculator-course-fields attendance-subject-fields">
        <div>
          <label class="form-label-lpu" for="attendance-subject-name-${index}">Subject name</label>
          <input class="form-control form-control-lpu" id="attendance-subject-name-${index}" type="text" maxlength="120" placeholder="Optional">
        </div>
        <div>
          <label class="form-label-lpu" for="attendance-subject-attended-${index}">Classes attended</label>
          <input class="form-control form-control-lpu attendance-subject-attended" id="attendance-subject-attended-${index}" type="number" min="0" step="1" required>
        </div>
        <div>
          <label class="form-label-lpu" for="attendance-subject-total-${index}">Total classes</label>
          <input class="form-control form-control-lpu attendance-subject-total" id="attendance-subject-total-${index}" type="number" min="1" step="1" required>
        </div>
        <div>
          <label class="form-label-lpu" for="attendance-subject-remaining-${index}">Classes remaining</label>
          <input class="form-control form-control-lpu attendance-subject-remaining" id="attendance-subject-remaining-${index}" type="number" min="0" step="1" value="0" required>
        </div>
        <button class="btn btn-outline-danger remove-course" type="button" aria-label="Remove subject">
          <i class="bi bi-trash" aria-hidden="true"></i>
        </button>
      </div>`;
    attendanceSubjects.appendChild(row);
    row.querySelector('.remove-course').addEventListener('click', () => {
      row.remove();
      attendanceResult.hidden = true;
      subjectDetailsWrap.hidden = true;
      attendanceError.hidden = true;
    });
  };

  addAttendanceSubject.addEventListener('click', addSubjectRow);
  addSubjectRow();
  calculateOverallAttendance.addEventListener('click', () => {
    attendanceError.hidden = true;
    const rows = Array.from(attendanceSubjects.querySelectorAll('.attendance-subject-row'));
    let attendedSum = 0;
    let totalSum = 0;
    let remainingSum = 0;
    for (const row of rows) {
      const attendedInput = row.querySelector('.attendance-subject-attended');
      const totalInput = row.querySelector('.attendance-subject-total');
      const remainingInput = row.querySelector('.attendance-subject-remaining');
      const attended = Number(attendedInput.value);
      const total = Number(totalInput.value);
      const remaining = Number(remainingInput.value);
      if (attendedInput.value === '' || totalInput.value === '' || remainingInput.value === '' || !Number.isInteger(attended) || !Number.isInteger(total) || !Number.isInteger(remaining) || attended < 0 || total < 1 || remaining < 0 || attended > total) {
        attendanceError.textContent = 'Enter whole class counts for every subject, with attended classes no greater than total classes.';
        attendanceError.hidden = false;
        attendanceResult.hidden = true;
        subjectDetailsWrap.hidden = true;
        return;
      }
      attendedSum += attended;
      totalSum += total;
      remainingSum += remaining;
    }
    if (!totalSum) {
      attendanceError.textContent = 'Add at least one subject with valid class counts.';
      attendanceError.hidden = false;
      attendanceResult.hidden = true;
      subjectDetailsWrap.hidden = true;
      return;
    }
    document.getElementById('overall-attendance-percent').textContent = `${(attendedSum * 100 / totalSum).toFixed(2)}%`;
    document.getElementById('projected-overall-attendance-percent').textContent = `${((attendedSum + remainingSum) * 100 / (totalSum + remainingSum)).toFixed(2)}%`;
    document.getElementById('overall-attendance-counts').textContent = `Current: ${attendedSum} of ${totalSum} classes attended across ${rows.length} subject${rows.length === 1 ? '' : 's'}. If you attend all ${remainingSum} remaining classes: ${attendedSum + remainingSum} of ${totalSum + remainingSum}.`;
    subjectDetails.replaceChildren();
    rows.forEach((row, index) => {
      const name = row.querySelector('input[id^="attendance-subject-name-"]').value.trim() || `Subject ${index + 1}`;
      const attended = Number(row.querySelector('.attendance-subject-attended').value);
      const total = Number(row.querySelector('.attendance-subject-total').value);
      const remaining = Number(row.querySelector('.attendance-subject-remaining').value);
      const needed = Math.max(0, Math.ceil((0.75 * total - attended) / 0.25));
      const canReach = needed <= remaining;
      const canMiss = canReach ? remaining - needed : 0;
      const projected = ((attended + remaining) * 100 / (total + remaining)).toFixed(2);
      const tr = document.createElement('tr');
      [name, `${(attended * 100 / total).toFixed(2)}% (${attended}/${total})`,
        canReach ? `${needed} of ${remaining} remaining` : `Not reachable (${needed} needed)`,
        canReach ? `${canMiss} of ${remaining}` : '0',
        canReach ? `Can reach 75%; attending all gives ${projected}%` : `Even attending all gives ${projected}%`].forEach((value, cellIndex) => {
        const cell = document.createElement(cellIndex === 0 ? 'th' : 'td');
        if (cellIndex === 0) cell.scope = 'row';
        cell.textContent = value;
        tr.appendChild(cell);
      });
      subjectDetails.appendChild(tr);
    });
    subjectDetailsWrap.hidden = false;
    attendanceResult.hidden = false;
  });

  const courseList = document.getElementById('course-list');
  const addCourseButton = document.getElementById('add-course');
  const modeSelect = document.getElementById('gpa-mode');
  const cumulativeFields = document.querySelector('.cumulative-fields');

  const updateCourseType = (select) => {
    const row = select.closest('.calculator-course-row');
    const isSatisfactory = select.value === 'satisfactory';
    row.querySelectorAll('.course-grade-inputs').forEach((field) => {
      field.hidden = isSatisfactory;
      const input = field.querySelector('input');
      input.required = !isSatisfactory;
    });
  };

  const updateMode = () => {
    const isCumulative = modeSelect.value === 'cgpa';
    cumulativeFields.hidden = !isCumulative;
    cumulativeFields.querySelectorAll('input').forEach((input) => {
      input.disabled = !isCumulative;
    });
  };

  courseList.querySelectorAll('.course-type').forEach((select) => {
    updateCourseType(select);
    select.addEventListener('change', () => updateCourseType(select));
  });
  modeSelect.addEventListener('change', updateMode);
  updateMode();

  addCourseButton.addEventListener('click', () => {
    const index = courseList.children.length + 1;
    const row = document.createElement('div');
    row.className = 'calculator-course-row';
    row.innerHTML = `
      <div class="calculator-course-fields">
        <div>
          <label class="form-label-lpu" for="course-name-${index}">Course name</label>
          <input class="form-control form-control-lpu" id="course-name-${index}"
                 name="course_name" type="text" maxlength="120" required>
        </div>
        <div class="course-grade-inputs">
          <label class="form-label-lpu" for="course-credits-${index}">Credits</label>
          <input class="form-control form-control-lpu" id="course-credits-${index}"
                 name="course_credits" type="number" min="0.001" step="0.001" required>
        </div>
        <div class="course-grade-inputs">
          <label class="form-label-lpu" for="course-marks-${index}">Marks / 100</label>
          <input class="form-control form-control-lpu" id="course-marks-${index}"
                 name="course_marks" type="number" min="0" max="100" step="0.01" required>
        </div>
        <div>
          <label class="form-label-lpu" for="course-type-${index}">Grading type</label>
          <select class="form-select form-control-lpu course-type" id="course-type-${index}"
                  name="course_type">
            <option value="graded">Credit-bearing</option>
            <option value="satisfactory">Satisfactory (S)</option>
          </select>
        </div>
        <button class="btn btn-outline-danger remove-course" type="button" aria-label="Remove course">
          <i class="bi bi-trash" aria-hidden="true"></i>
        </button>
      </div>`;
    courseList.appendChild(row);
    const select = row.querySelector('.course-type');
    select.addEventListener('change', () => updateCourseType(select));
    row.querySelector('.remove-course').addEventListener('click', () => row.remove());
    updateCourseType(select);
  });

  courseList.querySelectorAll('.remove-course').forEach((button) => {
    button.addEventListener('click', () => button.closest('.calculator-course-row').remove());
  });
})();
