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
