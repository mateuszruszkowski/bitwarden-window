# Security

Please use [private vulnerability reporting](https://github.com/mateuszruszkowski/bitwarden-window/security/advisories/new). If it is unavailable, contact the maintainer privately before sharing details. Include the affected commit, operating system, Bitwarden CLI version and expected behavior. Report using synthetic data only.

The window provides a limited command interface within one OS account. Its vault writes are create-only: the client can add a personal recovery note or login item, but it cannot read, edit or delete items. A `save` reply still tells the caller whether an existing login item with the given name holds the supplied secret. Software that can modify the user's shell, Bitwarden CLI, installed broker or configuration is outside this boundary. Keep your workstation and Bitwarden account protected. Rotating a compromised age identity also requires updating the recipients and recovery plan for affected backups.
