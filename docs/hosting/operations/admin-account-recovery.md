# Hosted Admin account and factor recovery

The platform owner manages Admin principals from a protected maintenance shell.
Use the approved deployment's identity setup and confirm the exact subject in
that Identity Platform project. The Admin store binds the verified realm alias
and subject. An email address by itself cannot identify the principal to change.

Stop the owning Admin writer before using the offline command. Run it as the
Admin store owner against the existing database, its pre-created writer lock,
and the protected setup file. Use canonical absolute paths and the matching
application resources. The CLI validates the database before changing it.

```bash
python -m app.modules.hosted_access.infrastructure.admin_bootstrap inspect \
  --database "$EPM_ADMIN_DATABASE" \
  --writer-lock "$EPM_ADMIN_WRITER_LOCK" \
  --setup "$EPM_IDENTITY_SETUP" \
  --application-directory "$EPM_APPLICATION_DIRECTORY" \
  --subject "$EPM_PROVIDER_SUBJECT"
```

Use the same arguments for these actions.

1. For initial setup, use `bootstrap` with the explicitly approved subject.
   Repeating the command for an enabled principal returns its existing state.
2. For a lost factor or suspected compromise, inspect the principal and run
   `suspend` with `--expected-revision` set to the inspected revision. This
   disables the principal and advances the generation checked by Admin sessions.
3. Recover the account with the identity provider. Have the provider administrator
   revoke existing provider sessions and remove compromised factors as appropriate.
   Confirm who controls the recovered account and verify its exact subject again.
4. For the same subject, inspect the suspended principal and use `restore` with
   the current revision. If the approved subject changed, leave the old principal
   suspended and bootstrap the replacement explicitly. Resume the owning writer.
5. Complete Google sign-in and the TOTP challenge. Verify that a previously
   issued Admin session is rejected. If the new proof fails, suspend the
   principal again and investigate.

Principal changes and their audit entries commit together. If the response is
lost, inspect the current revision and state before repeating a recovery action.
The CLI and SQLite effects have focused test coverage. The interactive sign-in
and live recovery procedure still require qualification with the Admin UI and
deployed routing.

## Build and start the Admin identity candidate

From `application/`, run `npm ci`, then `npm run build:admin` before building the
Python wheel. The wheel includes the compiled Admin HTML, JavaScript and CSS under
`app/admin_build/dist`. The module entry point is
`app.modules.hosted_access.infrastructure.admin_entry`.

Supply a private JSON deployment file with these fields.

| Field | Value |
| --- | --- |
| database | Absolute path to the existing Admin SQLite store |
| writer_lock | Absolute path to its existing stable writer lock |
| setup | Protected IdentitySetup JSON with verified provider configuration digest |
| provider_configuration | Protected provider configuration matching that digest |
| bearer_file | Private file supplying a current short-lived provider API bearer |
| mail_key_file | Private file containing at least 32 bytes of mail-admission key material |
| deployment_id | Owning deployment UUID |
| application_directory | Absolute directory containing the installed schema resources |
| support_contact | Platform-owner support email displayed during sign-in |

Files must belong to the service owner, have private permissions and use canonical
paths. Refresh the short-lived bearer through the protected credential delivery
owner. The entry point reads it for each provider API call. Stop the other Admin
writer before launching this candidate.

```bash
python -m app.modules.hosted_access.infrastructure.admin_entry \
  --configuration "$EPM_ADMIN_IDENTITY_CONFIGURATION" \
  --tls-key "$EPM_ADMIN_TLS_KEY" \
  --tls-certificate "$EPM_ADMIN_TLS_CERTIFICATE" \
  --port 8000
```

The listener binds loopback with TLS and acquires the owning writer lock for its
lifetime. Requests must carry the configured Admin host. H03.6 owns the gateway
mapping, Firebase helper and exact external HTTPS qualification. Complete provider
configuration acceptance before selecting this entry point for deployment.

The UI uses Firebase 13.3.0 with memory-only authentication persistence. After
authenticator enrollment, the operator signs in again to produce a signed completed
factor proof. Session status restores the sign-out control after a page reload.
The current focused browser tests exercise the unavailable sign-in and restored
session paths. Live Google popup, enrollment and TOTP acceptance remain qualification
work.
