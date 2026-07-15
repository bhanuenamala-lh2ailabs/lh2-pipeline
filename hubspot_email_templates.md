# HubSpot Email Templates — create once in HubSpot UI

> HubSpot's tier has no API for sales email templates, so create these
> manually: **Settings → Objects → Activities → Email templates** (or
> compose an email → Templates → Save as template). Replace
> `[CALENDLY_LINK]` with the lead owner's real Calendly URL.

## M1V1

**Use:** After a connected, interested cold call (Outcome 1).

**Subject:** `Following Up - LH2 Data Labs x {{company.name}}`

```
Hi {{contact.firstname}},

Great speaking with you earlier. As discussed, LH2 Data Labs acquires legacy codebases from established Indian IT-services firms like {{company.name}}.

I'd love to walk you through how the evaluation process works — it's quick and straightforward.

Pick a time that works for you: [CALENDLY_LINK]

Looking forward to connecting.

Best,
{{owner.first_name}}
LH2 Data Labs
```

## M1V2

**Use:** Cold email when the call wasn't picked up (Outcome 5).

**Subject:** `Quick question about {{company.name}}'s codebase`

```
Hi {{contact.firstname}},

I'm reaching out from LH2 Data Labs. We work with Indian IT-services firms to acquire legacy codebases — turning unused projects into real value.

Would love to have a quick 15-minute call to see if there's a fit.

Here's my calendar: [CALENDLY_LINK]

Best,
{{owner.first_name}}
LH2 Data Labs
```
