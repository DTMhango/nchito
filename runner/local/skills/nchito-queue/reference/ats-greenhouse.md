# Greenhouse

Hosts: `boards.greenhouse.io/<company>/jobs/<id>`, `job-boards.greenhouse.io/...`, or an
employer careers page embedding the Greenhouse form in an iframe (`grnh.se` links,
`?gh_jid=` in the URL). The embedded form is still Greenhouse; the domain to check is the
page's, as given in `stay_on_domain`.

- One page. "Apply for this job" may scroll to the form or reveal it; that click is fine.
- No account needed. A Greenhouse sign-in prompt is unusual: treat it as a `sign_in` blocker.
- Resume / cover letter: "Attach" opens a picker; use `file_upload` on the hidden
  `input[type=file]` (find it with `find`). "Enter manually" / "Paste" is not for us: attach
  the file.
- Custom questions follow the standard fields; most are selects or yes/no. Use `find_answer`
  for each one not in the packet.
- "Voluntary Self-Identification" (gender, race, veteran, disability) is US EEO. Always
  `find_answer`; normally `do_not_answer` with "Decline to self identify" / "I don't wish to
  answer".
- Location fields may autocomplete: type, wait, pick the suggestion that matches the packet
  value exactly; if none matches, leave the typed text.
- reCAPTCHA is often invisible and runs on Submit. If a challenge appears after the permit:
  do not solve it and do not click Submit again. `report_result` `uncertain` with `permit_id`
  and `detail` "CAPTCHA appeared after Submit; left open in Chrome for the owner", leave the
  tab open, and move on. Nchito's reconciliation picks it up from there.
- Confirmation: "Thank you for applying" / "Application submitted" on the same page. Usually
  no reference number.
