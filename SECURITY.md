# Security

Run this deployment on a trusted robot/operator network. The dashboard uses
rmf-web's development StubAuthenticator, which is unsuitable for an untrusted
or public network. Authentication/authorization for a public deployment is a
separate integration task using rmf-web's supported identity-provider setup.

Only the nginx dashboard/API port is published. RMF DDS traffic stays inside
the container; the adapter connects outbound to the configured Zenoh router.
The internal RMF reporting websocket is blocked at the public proxy.

Do not commit `.env`, private keys or robot/router credentials. To report a
vulnerability, use GitHub's private vulnerability reporting for this repository
if enabled; do not put credentials or exploit details in a public issue.
