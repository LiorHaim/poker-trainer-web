# Enabling MongoDB authentication on a running deployment

The database ran with no authentication and no network restriction: any pod
scheduled into the namespace could read every account, every password hash and
the whole decision history. Demonstrated by running a throwaway pod:

```
connected with NO credentials from an unrelated pod
collections: history, reviews, totals, users
user accounts readable: 6
password hashes exposed: yes
```

`openshift.yaml` now carries the fix, but **a fresh `oc apply` is not enough for
a database that already has data**. The steps below were validated end to end in
a scratch namespace before being written down.

## The trap

The obvious approach is `MONGO_INITDB_ROOT_USERNAME` / `MONGO_INITDB_ROOT_PASSWORD`.
It does not work on an existing volume, and it fails in the worst possible way:

| | |
|---|---|
| What you expect | auth on, root user created |
| What happens | auth on, **no user created** |

The entrypoint adds `--auth` whenever those variables are set, but only creates
the user when the data directory is empty. On a populated volume you end up with
`mongod --auth --bind_ip_all` and zero users — the application is locked out
completely and only MongoDB's localhost exception remains. Measured in scratch:

```
$ oc exec deploy/mongodb -- mongo --quiet admin --eval 'db.system.users.count()'
cannot even count users: Unauthorized
$ cat /proc/1/cmdline
mongod --auth --bind_ip_all
```

So the manifest sets `args: ["--auth", "--bind_ip_all"]` explicitly, and the
users are created **before** auth is switched on.

## Procedure

Expect roughly 30 seconds where the app cannot reach the database, between the
MongoDB rollout and the app rollout. Readiness takes the pods out of the load
balancer and puts them back automatically; no restarts occur.

```bash
oc project poker-trainer

# 1. Credentials. Generates them only if absent - rotating would lock the app out.
make ensure-secret
PASS=$(oc get secret poker-trainer-secrets -o jsonpath='{.data.mongo-password}' | base64 -d)

# 2. Create the users while auth is still OFF.
oc exec deploy/mongodb -- mongo --quiet admin --eval "
  db.getSiblingDB('poker').createUser({
    user: 'poker', pwd: '$PASS',
    roles: [{role: 'readWrite', db: 'poker'}]
  });"

# 3. Turn auth on and point the app at the credentials. Both live in the manifest.
oc apply -f openshift.yaml
oc rollout status deploy/mongodb
oc rollout status deploy/poker-trainer
```

## Verify

```bash
# Readiness recovers on its own.
curl -s https://$(oc get route poker-trainer -o jsonpath='{.spec.host}')/api/health/ready

# An unrelated pod can no longer reach the database at all.
oc run rogue --image=docker.io/library/mongo:5.0 --restart=Never --rm --attach -- \
  mongo --quiet "mongodb://mongodb:27017/poker" --eval 'db.users.count()'
# expected: connection timed out, blocked by the NetworkPolicy

# Data is intact.
oc exec deploy/mongodb -- mongo --quiet "mongodb://poker:$PASS@localhost:27017/poker" \
  --eval 'db.users.count() + " users, " + db.history.count() + " hands"'
```

## Rolling back

Remove `args` from the mongodb container and revert the app's `MONGO_URI`. The
users stay in the database but are not enforced, so nothing is lost.

## Why the NetworkPolicy is scoped to the database

It selects the `mongodb` pod and admits only pods labelled `app=poker-trainer`.
A namespace-wide default-deny would also need an explicit allow for the
OpenShift router to reach the app, and getting that selector wrong takes the
whole app offline. Scoping to the database achieves the same goal — only the
app can talk to it — with no path to that failure.
