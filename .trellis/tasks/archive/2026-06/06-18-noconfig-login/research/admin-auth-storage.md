# Admin Auth Storage Research

## Question

For the noconfig admin page, what is the safer and more maintainable way to implement "account/password login + remember me"?

## Repo constraints

* Current implementation uses a shared `api_token` in query string and `localStorage`.
* There is no existing session middleware pattern in `remote/`.
* Admin UI and its iframe are same-origin under the same FastAPI app, which makes cookie-based auth practical.
* Existing machine-to-machine callbacks (`/register`, `/push`, `/presence`, `/register-room`) already depend on `api_token`, so web-admin auth can be layered separately for MVP.

## Source findings

### OWASP session guidance

* OWASP says cookies are the preferred exchange mechanism for session IDs because they support expiration and other protective attributes, while URL-based session IDs can leak into logs, browser history, bookmarks, and referrers.
* OWASP recommends using cookies as the session tracking mechanism and avoiding accepting session IDs through other mechanisms such as URL parameters.
* OWASP also recommends regenerating the session ID after authentication to defend against session fixation.

Source:
* [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)

### MDN session-storage guidance

* MDN says cookies are the recommended storage choice for session identifiers because `HttpOnly` can keep them out of JavaScript access.
* MDN notes that if a session identifier is available to JavaScript, such as via local storage, XSS can steal it.
* MDN also says cookies are a better transport/storage mechanism for session IDs than URL parameters.

Sources:
* [MDN Session management](https://developer.mozilla.org/en-US/docs/Web/Security/Authentication/Session_management)
* [MDN Using HTTP cookies](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Cookies)

### Starlette implementation fit

* Starlette `SessionMiddleware` provides signed cookie-based sessions.
* The session cookie is `HttpOnly`.
* It supports `max_age` for remember-me duration, `same_site`, and `https_only`.

Source:
* [Starlette middleware docs](https://www.starlette.io/middleware/)

## Feasible approaches in this repo

### Approach A: Cookie session for web admin, keep api_token for machine callbacks

How it works:
* Add account/password login endpoints for admin UI only.
* After successful login, set a signed session cookie.
* Protect `/admin` and admin-only JSON endpoints with session checks.
* Keep existing `api_token` validation for extractor / proxy / ECS callbacks and, if needed, for internal page-to-iframe compatibility during migration.

Pros:
* Best fit with OWASP/MDN guidance.
* Same-origin admin + iframe flow works naturally with cookies.
* Lowest blast radius for existing game-side integrations.
* Supports remember-me with cookie `max_age`.

Cons:
* Creates two auth mechanisms temporarily: session for humans, token for service callbacks.
* Requires clear route partitioning so admin APIs and machine callbacks do not get mixed up.

### Approach B: Login form that still writes api_token to browser storage

How it works:
* User enters account/password.
* Backend validates and returns the same shared token or a derived token.
* Frontend stores it in local storage and continues calling current endpoints with `?token=`.

Pros:
* Minimal code churn.
* Smaller backend change initially.

Cons:
* Preserves the current weaknesses around query-string and JS-visible token handling.
* "Login" becomes mostly cosmetic rather than a true session boundary.
* Harder to justify as the long-term design.

### Approach C: Replace all auth, including machine callbacks, with account/session model

How it works:
* Remove shared token model.
* Introduce new auth for admin UI and service-to-service paths.

Pros:
* Cleaner end state eventually.

Cons:
* Too much scope for this request.
* Risks breaking extractor, ECS proxy, and current deployment behavior.

## Recommendation

Recommend **Approach A** for MVP:

* Add a real account/password login for the admin web surface.
* Persist remembered login with a signed, `HttpOnly` session cookie.
* Keep current `api_token` for machine callbacks and possibly hidden internal compatibility during transition.
* Over time, we can decide whether admin-facing JSON endpoints should fully stop accepting `?token=` once the UI no longer depends on it.
