# Authentication


LARS includes a built-in authentication system for securing the SQL server and Studio web interface.
  Authentication is **enabled by default** with a default admin account.
**On This Page**
- [Overview](#overview)
- [Default Credentials](#default-credentials)
- [User Management](#user-management)
- [API Keys](#api-keys)
- [SQL Client Authentication](#sql-client-auth)
- [Studio Authentication](#studio-auth)
- [Configuration](#configuration)
- [CLI Reference](#cli-reference)


## Overview


LARS authentication provides:
- **User accounts** with password hashing (Argon2)
- **API keys** for programmatic access (JWT-based)
- **PGwire authentication** for SQL clients (DBeaver, psql, DataGrip)
- **Bearer token authentication** for REST API and Studio
- **Session scoping** for user-specific parameters and data


> **NOTE: Enabled by Default**
>
> 
> Authentication is **enabled by default** starting from LARS 0.x.
>     A default `admin` user is automatically created on first initialization.
>     You can disable authentication for development by setting `LARS_AUTH_ENABLED=0`.
> 


## Default Credentials


When LARS initializes for the first time, it creates a default admin account:


| Field    | Value   |
|----------|---------|
| Username | `admin` |
| Password | `admin` |


> **WARNING: Change Default Password**
>
> 
> For production use, change the default admin password immediately:
> 
```
lars auth set-password admin
```


## User Management


### Create a User


```bash
# Create a new user (prompts for password)
lars auth create-user alice

# Create with email
lars auth create-user bob --email bob@example.com

# Create an admin user
lars auth create-user superadmin --admin
```

### List Users


```bash
# List all users
lars auth list-users

# Output as JSON
lars auth list-users --json
```

### Change Password


```bash
# Change password (prompts for new password)
lars auth set-password alice
```

### Enable/Disable Users


```bash
# Disable a user (prevents login)
lars auth disable-user alice

# Re-enable a user
lars auth enable-user alice
```

## API Keys


API keys provide programmatic access for SQL clients, scripts, and integrations.
  Each key is a JWT token with an optional expiration date.

### Create an API Key


```bash
# Create a key for a user
lars auth create-key alice --name "DBeaver"

# Create with expiration
lars auth create-key alice --name "CI Pipeline" --expires 30d

# Create with longer expiration
lars auth create-key bob --name "Data Team" --expires 1y
```


The command outputs the full API key. **Save it immediately** - it cannot be retrieved later.

```output
Created API key for alice:
  Name: DBeaver
  Key: lars_abc123...xyz789
  Expires: never

Save this key - it cannot be retrieved later!
```

### List API Keys


```bash
# List all keys
lars auth list-keys

# List keys for a specific user
lars auth list-keys --user alice

# Output as JSON
lars auth list-keys --json
```

### Revoke an API Key


```bash
# Revoke by key prefix (first 8 characters)
lars auth revoke-key lars_abc

# Revoke with reason
lars auth revoke-key lars_abc --reason "Employee departure"
```

## SQL Client Authentication


SQL clients authenticate via the PostgreSQL wire protocol. You can use either:
- **Password authentication**: Username + password
- **API key authentication**: Username + API key as password


### Using Password


```bash
# Connect with psql using password
psql -h localhost -p 15432 -U admin -d default
# Enter password when prompted: admin

# Or use connection URL
psql postgresql://admin:admin@localhost:15432/default
```

### Using API Key


```bash
# Connect with API key as password
psql -h localhost -p 15432 -U alice -d default
# Enter API key when prompted: lars_abc123...

# Or use connection URL (URL-encode the key if needed)
psql postgresql://alice:lars_abc123...@localhost:15432/default
```

### DBeaver / DataGrip Configuration


| Setting  | Value                           |
|----------|---------------------------------|
| Host     | `localhost`                     |
| Port     | `15432`                         |
| Database | `default` or your database name |
| Username | Your LARS username              |
| Password | Your password **or** API key    |


> **TIP: API Keys for SQL Clients**
>
> 
> For SQL clients that save credentials, using an API key instead of your password is recommended.
>     API keys can be revoked individually without changing your account password.
> 


## Studio Authentication


LARS Studio uses the same authentication system. When you open Studio, you'll see a login page.

### Login
1. Open [http://localhost:5050](http://localhost:5050)
2. Enter your username and password (default: `admin` / `admin`)
3. Click "Sign In"


### User Menu


Once logged in, a user menu appears in the bottom-right corner of the screen.
  Click it to access account options including logout.

### REST API Authentication


For programmatic access to the Studio REST API, use Bearer token authentication:

```bash
# Execute SQL via REST API
curl -X POST http://localhost:5050/api/sql/execute \
  -H "Authorization: Bearer lars_abc123..." \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT 1 + 1 AS result"}'
```

## Configuration


Authentication behavior is controlled by environment variables:


| Variable                       | Default          | Description                                                     |
|--------------------------------|------------------|-----------------------------------------------------------------|
| `LARS_AUTH_ENABLED`            | `1`              | Enable/disable authentication. Set to `0` to disable.           |
| `LARS_AUTH_SECRET_KEY`         | (auto-generated) | Secret key for JWT signing. Auto-generated if not set.          |
| `LARS_AUTH_KEY_DEFAULT_EXPIRY` | `365d`           | Default expiration for API keys when `--expires` not specified. |


### Disable Authentication


For local development or testing, you can disable authentication:

```bash
# Disable authentication
export LARS_AUTH_ENABLED=0

# Start servers - no login required
lars serve sql
lars serve studio
```


> **WARNING: Production Warning**
>
> 
> Never disable authentication in production environments.
>     Always use strong passwords and consider network-level security (firewalls, VPNs)
>     in addition to LARS authentication.
> 


## CLI Reference


Complete list of authentication CLI commands:

```bash
# User management
lars auth create-user <username> [--email EMAIL] [--admin]
lars auth list-users [--json]
lars auth set-password <username>
lars auth enable-user <username>
lars auth disable-user <username>

# API key management
lars auth create-key <username> --name NAME [--expires DURATION]
lars auth list-keys [--user USERNAME] [--json]
lars auth revoke-key <key_prefix> [--reason REASON]

# Status
lars auth status
```

### Expiration Duration Format


The `--expires` flag accepts these formats:


| Format | Example | Description             |
|--------|---------|-------------------------|
| `Nd`   | `30d`   | N days                  |
| `Nw`   | `2w`    | N weeks                 |
| `Nm`   | `6m`    | N months (30 days each) |
| `Ny`   | `1y`    | N years                 |


> **TIP: Quick Setup**
>
> 
> For a quick multi-user setup:
> 
```
# Create users
lars auth create-user analyst1
lars auth create-user analyst2

# Create long-lived API keys for SQL clients
lars auth create-key analyst1 --name "DBeaver" --expires 1y
lars auth create-key analyst2 --name "DataGrip" --expires 1y
```
