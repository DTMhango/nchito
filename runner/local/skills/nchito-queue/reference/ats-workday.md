# Workday

Hosts: `<tenant>.wd<N>.myworkdayjobs.com/...` or `<tenant>.wd<N>.myworkdaysite.com/...`. Each
employer is a separate tenant with its own account.

- **Workday always needs an account per employer.** If the owner has not signed in to this
  tenant in this Chrome, you will meet "Sign In" / "Create Account" after "Apply". That is a
  `sign_in` (or `create_account`) blocker with the tenant URL. Never fill the sign-in or
  create-account forms, never use "Apply with LinkedIn", "Autofill with Resume" sign-in
  flows, or "Use my last application" if it asks for a password.
- Signed in already (the owner did it): the flow is several pages: My Information, My
  Experience, Application Questions, Voluntary Disclosures, Self Identify, Review. "Save and
  Continue" moves between pages and **also saves the data to the employer's system**. Treat
  each "Save and Continue" as releasing that page's data: only press it when every value on
  the page is from the packet or `find_answer`. Checkpoint after each page.
- "Autofill with Resume" re-parses the CV and fills My Experience. Do not use it; fill from
  the packet. If the tenant has pre-filled from an earlier application, compare each value
  with the packet and correct differences.
- Work history and education are repeated blocks ("Add"). Add only as many as the packet has.
  Dates are often split month/year selects.
- Dropdowns are custom widgets: click, type to filter, pick the exact match. Re-read after
  each to confirm it took.
- "Voluntary Disclosures" often includes terms and a declaration checkbox ("I certify..."):
  that is a `declaration` blocker unless `find_answer` for that exact text returns a value.
- "Self Identify" (disability) forms: `find_answer`; normally `do_not_answer`.
- The final button is "Submit" on the Review page. That, and only that, needs the permit.
  Request the permit on the Review page after re-reading every section shown there.
- Session timeouts happen. If you are signed out midway: checkpoint, `sign_in` blocker.
- Confirmation: "Application Submitted" dialog or page; the candidate home then lists it.
