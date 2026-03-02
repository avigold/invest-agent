# User Roles — investagent.app

Last updated: 2026-03-01

---

## Overview

Every user has a `role` column on the `users` table. The role determines access level across the platform. Roles are orthogonal to billing plans — a user's effective capabilities are the union of their role permissions and their plan entitlements.

**Valid roles**: `user`, `admin`
**Default role**: `user` (assigned at account creation)

---

## Role: `user`

The standard role for all registered accounts.

### Permissions
- View and interact with all public platform features (countries, industries, companies, recommendations)
- Submit research jobs (subject to plan limits)
- Manage own scoring profiles (create, edit, delete, activate)
- View own job history and stream job logs
- Manage own Stripe subscription (upgrade, downgrade, cancel via portal)

### Restrictions
- Cannot access `/api/admin/*` endpoints (HTTP 403)
- Cannot see or modify other users' data
- Cannot change any user's role
- Subject to plan-based job quotas (Free plan monthly limits)

---

## Role: `admin`

Platform operator role. Grants full access to all features plus administrative capabilities.

### Permissions

Everything in `user`, plus:

- **Plan override**: Effective plan is always `pro`, regardless of subscription status. Implemented via `effective_plan()` in `app/api/deps.py`.
- **Admin dashboard**: Access to `/admin` page (stats cards, user management, job monitoring)
- **User management**: View all users, change any user's role via `POST /api/admin/users/{user_id}/role`
- **Job visibility**: View all jobs across all users (last 200) via `GET /api/admin/jobs`
- **Platform stats**: View aggregate metrics (total users, pro subscribers, jobs today, running/queued counts) via `GET /api/admin/stats`
- **Bypass job quotas**: No monthly job limits (effective plan = `pro`)

### Admin API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/admin/stats` | Aggregate platform stats |
| `GET` | `/api/admin/users` | List all users with subscription and activity info |
| `GET` | `/api/admin/jobs` | Last 200 jobs across all users |
| `POST` | `/api/admin/users/{user_id}/role` | Update a user's role |

All admin endpoints use the `require_admin` dependency, which returns HTTP 403 if `user.role != "admin"`.

---

## Role assignment

- **At registration**: All new users receive `role = "user"`.
- **Promotion/demotion**: Only an existing admin can change a user's role via the admin dashboard or API.
- **Self-demotion**: An admin can demote themselves. There is no guard against removing the last admin — this is by design for simplicity.
- **Database column**: `users.role` (varchar, not null, default `"user"`).
- **Validation**: Role updates are validated against the set `{"user", "admin"}`. Invalid values are rejected with HTTP 422.

---

## Frontend behavior

- **Nav bar**: The "Admin" link appears only when `user.role === "admin"`.
- **Admin page**: Non-admin users are redirected to `/dashboard` on load.
- **Plan badge**: Admins always display "pro" as their effective plan.

---

## Interaction with billing plans

| Role | Subscription | Effective plan | Job limits |
|---|---|---|---|
| `user` | None / Free | `free` | Monthly quotas apply |
| `user` | Pro (active/trialing) | `pro` | Unlimited |
| `admin` | Any or none | `pro` | Unlimited |

The `effective_plan()` function resolves this: admins always return `"pro"`, others return their actual plan from the subscription system.
