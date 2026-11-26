# Lever

Hosts: `jobs.lever.co/<company>/<uuid>`; the form is at `.../<uuid>/apply`. Some employers use
`jobs.eu.lever.co`.

- One page, no account.
- "Resume/CV" upload sits at the top. Lever then tries to parse the CV and pre-fill name,
  email, phone, company. After the upload, re-read the form and overwrite any pre-filled
  value that differs from the packet. Never keep a parsed value the packet does not have.
- "Links" (LinkedIn, GitHub, Portfolio, Other): fill only from packet fields; leave the rest
  blank.
- "Additional information" free text: only a packet answer meant for it (for example a
  cover note); otherwise `find_answer` with the label, and blank if nothing comes back.
- Custom question cards appear below; EEO "U.S. Equal Employment Opportunity" survey at the
  bottom is optional: `find_answer`, normally `do_not_answer`.
- hCaptcha may run on "Submit application". Same handling as Greenhouse: never solve it;
  if it appears after the click, report `uncertain` and leave the tab open.
- Confirmation: a page saying "Application submitted" / "Thanks for applying"; URL often ends
  in `/thanks`.
