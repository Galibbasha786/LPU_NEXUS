# Campus AI assistant setup

The campus assistant uses Google Gemini from the Django server. No API key is
needed in the browser.

Set these environment variables for the application process:

```text
GEMINI_API_KEY=your-google-ai-studio-api-key
GEMINI_MODEL=gemini-2.5-flash
```

The model name defaults to `gemini-2.5-flash`. Keep the API key private and do
not commit it to the repository. Restart Django after setting the variables.
Without `GEMINI_API_KEY`, the assistant reports that it is unavailable.

## Student data and privacy

Each assistant and problem-triage request requires the student to opt in.
Requests are sent to Google Gemini only after consent. The server never sends
the student's account name, email, or UID as account fields; obvious email
addresses, phone numbers, and long identifiers in the entered text are
redacted. Name detection is not reliable, so the UI instructs students not to
enter names or other private information. AI requests are not stored by this
feature.

Campus Q&A is grounded in the campus locations and LPU Nexus feature
information available to the application. It must not be used for emergencies.
Problem triage only suggests a category, priority, and staff team; students
choose what to apply and staff retain responsibility for decisions. A
server-side keyword check blocks obvious emergency-like reports before any AI
request, and emergency reports continue through the separate responder workflow.

## Voice controls

The campus assistant offers optional browser speech recognition to transcribe
questions into the text box, and browser speech synthesis to read answers aloud.
Recognition support depends on the user's browser and microphone permission.
The transcript is not submitted automatically: the student reviews it and
presses Ask, with the same Gemini consent as typed questions.
