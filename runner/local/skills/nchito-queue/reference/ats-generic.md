# Other sites

Anything not Greenhouse, Lever, Ashby or Workday: employer careers pages, SmartRecruiters,
Teamtailor, BambooHR, Recruitee, Workable, iCIMS, Taleo, SuccessFactors, job boards' own
"easy apply" forms.

- Find the form first. If the posting has an "Apply" button that leads to another domain,
  check it against `stay_on_domain` before going there; a different domain is
  `redirect_off_domain`.
- "Apply with LinkedIn / Indeed / Google / SEEK" and any single sign-on button: do not use.
  If it is the only way in, `sign_in` blocker.
- iCIMS, Taleo and SuccessFactors almost always need an account: expect a `sign_in` or
  `create_account` blocker, as for Workday.
- "Email your CV to ..." instead of a form: do not send email from the browser. Raise
  `unsupported_form` with the address in `detail`; Nchito's email channel handles those.
- Upload-only forms (CV plus contact details): fine; same rules.
- Free-text boxes ("Why do you want to work here?", "Anything else?"): only a packet answer
  for that question or a `find_answer` value. Never write your own text.
- Multi-step forms: a "Next" or "Continue" moves on without a permit only when the page shows
  more steps follow (a step indicator, or later-step fields still to come). Any button that
  might send the application counts as Submit: request the permit only when it is the last
  thing left. If fields would still follow a button you cannot classify, `unsupported_form`.
- Pop-ups (cookie banners, newsletter sign-ups, chat widgets): decline or close them; never
  accept marketing, never type into chat widgets. Cookie banners: choose "reject
  non-essential" or the most limited option.
- Anything you do not recognise, or a form that does not respond as expected after two
  attempts: `unsupported_form` with what you saw.
- Confirmation: look for a clear success message, an email-sent notice or a reference
  number. A plain redirect to the careers home with no message is `uncertain`.
