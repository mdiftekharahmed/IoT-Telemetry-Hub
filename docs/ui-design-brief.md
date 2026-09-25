# UI design and implementation

Implemented directly in the repository using plain HTML/CSS/JavaScript, based on
the user's two supplied screenshots. The user chose local implementation instead
of a Google Stitch handoff. This document preserves the page requirements.

Design five pages for a small IoT telemetry administration tool used by one admin.
Keep the interface simple and responsive. A separate dashboard is not required.

## Shared layout

Authenticated pages share navigation: Devices, Allowed Parameters, Stored Data,
CSV Export. Show the current admin and a Logout action. Include desktop and mobile
layouts, loading states, request-failure feedback and session-expired handling.
Do not add analytics, charts, alerts, GPS/maps, firmware controls or complex roles.

## 1. Login

Username, password, show/hide password and Sign in. Include submitting and generic
invalid-credentials states. Initial account provisioning and password resets happen
through an operator CLI; no registration or forgot-password screens are needed yet.

## 2. Devices

Table: device ID, name, enabled/disabled status, creation date. Show a registered
device count such as "3 of 10 devices". Add a device using ID, name and enabled state.
Allow editing the name and enabled state; the ID remains immutable.

Include empty list, duplicate/invalid ID errors and ten-device capacity state.
Enabling/disabling controls data acceptance; it does not represent online/offline
status. No device deletion or live health indicators in this version.

## 3. Allowed Parameters

Table: parameter name, enabled/disabled status and actions. Add a parameter, toggle
its enabled state or remove it with confirmation. This whitelist applies globally
to all devices. Names are case-sensitive and immutable after creation.

Parameter names: letter first, then letters/digits/underscores, maximum 64 characters.
Show helper text: "Only enabled parameters are stored. Removing a parameter does
not delete previously collected data." Include empty, invalid and duplicate states.

## 4. Stored Data

Read-only table: timestamp, device ID, parameter and numeric value. Label the timezone.
Newest received records appear first. Include Previous/Next or Load more navigation,
loading, empty and request-failure states. The API uses a cursor for older records;
avoid a numbered-page total unless added to the API later.

This is a simple verification view; no charts, editing, advanced filters or real-time
connection status are needed.

## 5. CSV Export

Start date/time, end date/time, clear timezone label and Download CSV button. Include
missing-date, end-before-start, preparing/downloading and download-error states.
The UI converts selected times into timestamps with explicit UTC offsets for the API.

Explain that the start is included and the end is excluded. Exports contain
`timestamp, device_id, parameter, value`; an interval with no records downloads a
CSV with column headers only. No device/parameter filters or format selector.

## Source files

`app/templates/login.html` and `app/templates/app.html` provide the page structure.
`app/static/styles.css` contains all responsive styling. `app/static/app.js` and
`app/static/login.js` connect the pages to the API. Icons are local SVG assets.

Mobile navigation opens as a drawer. Forms stack on narrow viewports, and only the
table region scrolls horizontally. Colors use navy and emerald, with pale surfaces,
subtle borders and small colored parameter labels. No external fonts or UI packages.
