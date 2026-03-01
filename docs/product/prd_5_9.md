# PRD 5.9 — Admin Dashboard

**Product**: investagent.app
**Status**: Complete

## Summary

Admin dashboard for platform operators. Provides at-a-glance stats, user management (role assignment), and recent job visibility. Accessible only to users with `role = "admin"`.

## Features

### 1. Admin Role Gating
- Users have a `role` column (`user` or `admin`; default `user`)
- `require_admin` dependency rejects non-admin requests with 403
- Frontend nav shows "Admin" link only when `user.role === "admin"`
- Admin page redirects non-admin users to `/dashboard`

### 2. Stats Cards
- **Total Users**: count of all registered users
- **Pro Subscribers**: count of active/trialing subscriptions with plan `pro`
- **Jobs Today**: count of jobs queued today (UTC)
- **Running / Queued**: live counts of in-flight jobs

### 3. Users Table
- Columns: Email, Name, Role (editable dropdown), Plan (badge), Jobs (count), Last Active, Joined
- Role dropdown allows promoting/demoting users between `user` and `admin`
- Plan badge shows effective plan (admins always get `pro`)
- Subscription plan and status shown alongside effective plan

### 4. Jobs Table
- Last 200 jobs across all users, newest first
- Columns: ID (clickable link to job detail), Command, Status (colored badge), User, Params, Queued
- Status colors: blue (running), green (done), red (failed), yellow (queued), gray (cancelled)

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/admin/stats` | Aggregate dashboard stats |
| `GET` | `/api/admin/users` | List all users with job counts and subscription info |
| `GET` | `/api/admin/jobs` | Last 200 jobs with user info |
| `POST` | `/api/admin/users/{user_id}/role` | Update a user's role |

All endpoints require `require_admin` dependency.

## Files

| File | Action |
|---|---|
| `app/api/routes_admin.py` | New — admin API endpoints |
| `app/main.py` | Modified — registered admin router |
| `web/src/pages/Admin.tsx` | New — admin dashboard page |
| `web/src/App.tsx` | Modified — added `/admin` route |
| `web/src/components/NavBar.tsx` | Modified — conditional admin nav link |

## Design

Matches the dark theme of the rest of the app. Purple accent color for admin-specific elements. Modeled after the admin panel in the companion project (my-second).
