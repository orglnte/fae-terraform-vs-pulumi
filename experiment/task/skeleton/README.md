# The stack

Deploy the service in image `iac-app:1` to the Docker daemon that
`DOCKER_HOST` names. Two inputs:

| input | values | default |
|---|---|---|
| `env` | `dev` or `prod` | `dev` |
| `replicas` | number of app containers, 1 or more | `1` |

## What the stack must be

1. **The app.** `replicas` containers of `iac-app:1`. It listens on port
   8000 and reads:
   - `DATABASE_URL` = `postgresql://app:<password>@<postgres host>:5432/app`
   - `REDIS_URL` = `redis://<redis host>:6379/0`, in `prod` only
   It exits if a store it was given does not answer within 5 seconds of
   starting, so it must start only after its stores are ready.
2. **nginx** (`nginx:1.30.5-alpine`) spreads requests across every app
   replica and is the only container that publishes a port: `8080` on the
   daemon's host.
3. **Postgres** (`postgres:16-alpine`): user `app`, database `app`, its data
   on a named volume.
4. **Redis** (`redis:7-alpine`), in `prod` only.
5. **Private stores.** Postgres and Redis publish no port, and share no
   network with nginx: only the app containers reach them.
6. **A generated password.** The database password is generated (16
   characters or more) and kept in the tool's state, never written in your
   files.
7. **Changing `replicas`** changes the app containers and nginx only: the
   Postgres container and its data stay.
8. **Applying twice** with the same inputs changes nothing the second time.
9. **Destroy** removes every container, network and volume the stack
   created, and no image.
10. **Images.** All four images are already in the daemon. Use them as they
    are: no build, no pull.

## The app's API

| request | answer |
|---|---|
| `GET /health` | `200 {"ok": true, "cache": <REDIS_URL set>, "replica": <hostname>}` |
| `POST /items` `{"name": "x"}` | `201 {"id": 1, "name": "x", ...}` |
| `GET /items/<id>` | `200 {"id": 1, "name": "x", "cached": <from Redis>, ...}` |

## How it is verified

Each attempt deploys the stack twice, on an empty daemon each time:

- **prod**: apply with `env=prod replicas=3` → 40 requests through
  `:8080` reach 3 distinct replicas, each reporting the cache → an item
  written and read back → only nginx publishes a port, the stores share no
  network with it → the password is 16+ characters and in none of your
  files → a second plan with the same inputs is empty → apply
  `replicas=5`: 5 replicas, the same Postgres container, the item still in
  the table → destroy leaves no container, network or volume, and every
  image.
- **dev**: apply with `env=dev replicas=1` → one replica, no Redis, the
  same privacy and password checks → destroy leaves nothing.

The first failed check ends the attempt; its message is your feedback.
