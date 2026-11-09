(() => {
  const dialog = document.getElementById('social-share-dialog');
  if (!dialog) return;

  const search = document.getElementById('social-share-student-search');
  const results = document.getElementById('social-share-student-results');
  const selection = document.getElementById('social-share-selection');
  const status = document.getElementById('social-share-status');
  const sendButton = document.getElementById('social-share-send');
  const csrfToken = dialog.querySelector('[name="csrfmiddlewaretoken"]').value;
  let shareUrlTemplate = '';
  let postId = '';
  let selectedStudent = null;
  let currentQuery = '';
  let searchTimer;

  function resetDialog(button) {
    shareUrlTemplate = button.dataset.shareUrlTemplate;
    postId = button.dataset.postId;
    selectedStudent = null;
    currentQuery = '';
    search.value = '';
    results.replaceChildren();
    selection.textContent = '';
    status.textContent = '';
    sendButton.disabled = true;
    dialog.showModal();
    search.focus();
  }

  document.querySelectorAll('[data-post-share]').forEach(button => {
    button.addEventListener('click', () => resetDialog(button));
  });
  dialog.querySelectorAll('[data-share-dialog-close]').forEach(button => {
    button.addEventListener('click', () => dialog.close());
  });

  function chooseStudent(student) {
    selectedStudent = student;
    selection.textContent = `Share this post with ${student.full_name} (${student.registration_number})?`;
    sendButton.textContent = `Send to ${student.full_name}`;
    sendButton.disabled = false;
  }

  search.addEventListener('input', () => {
    window.clearTimeout(searchTimer);
    selectedStudent = null;
    selection.textContent = '';
    sendButton.disabled = true;
    status.textContent = '';
    results.replaceChildren();
    const query = search.value.trim();
    currentQuery = query;
    if (query.length < 2) return;

    searchTimer = window.setTimeout(async () => {
      try {
        const url = new URL(search.dataset.searchUrl, window.location.origin);
        url.searchParams.set('q', query);
        const response = await fetch(url, {headers: {'Accept': 'application/json'}});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Student search failed.');
        if (query !== currentQuery) return;
        if (!data.results.length) {
          const empty = document.createElement('p');
          empty.className = 'social-suggestion-empty';
          empty.textContent = 'No verified student found.';
          results.appendChild(empty);
        }
        data.results.forEach(student => {
          const option = document.createElement('button');
          option.type = 'button';
          option.className = 'social-student-suggestion';
          option.setAttribute('role', 'option');
          const avatar = document.createElement('span');
          avatar.className = 'social-suggestion-avatar';
          if (student.profile_image_url) {
            const image = document.createElement('img');
            image.src = student.profile_image_url;
            image.alt = '';
            avatar.appendChild(image);
          } else {
            avatar.textContent = student.full_name.slice(0, 1);
          }
          const details = document.createElement('span');
          details.className = 'social-suggestion-details';
          const name = document.createElement('strong');
          name.textContent = student.full_name;
          const profile = document.createElement('small');
          profile.textContent = [
            student.registration_number,
            student.department,
            student.year ? `Year ${student.year}` : '',
          ].filter(Boolean).join(' · ');
          details.append(name, profile);
          option.append(avatar, details);
          option.addEventListener('click', () => chooseStudent(student));
          results.appendChild(option);
        });
      } catch (error) {
        results.replaceChildren();
        status.textContent = error.message;
      }
    }, 250);
  });

  sendButton.addEventListener('click', async () => {
    if (!selectedStudent || !shareUrlTemplate) return;
    sendButton.disabled = true;
    status.classList.remove('text-danger');
    status.classList.add('text-muted');
    status.textContent = 'Sending post to the direct chat...';
    try {
      const url = shareUrlTemplate.replace('POST_ID', encodeURIComponent(
        postId,
      ));
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrfToken,
          'Accept': 'application/json',
          'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        },
        body: new URLSearchParams({
          csrfmiddlewaretoken: csrfToken,
          peer_id: selectedStudent.id,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'The post could not be shared.');
      window.location.assign(data.url);
    } catch (error) {
      status.classList.remove('text-muted');
      status.classList.add('text-danger');
      status.textContent = error.message;
      sendButton.disabled = false;
    }
  });
})();
