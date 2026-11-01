// SPDX-License-Identifier: AGPL-3.0-or-later
//! The desktop app's own secrets: the vault's master key and the database
//! passwords. They live in the OS keychain (Windows Credential Manager or
//! the macOS Keychain), never in the data folder, so a copied data folder
//! can't be opened without this user's keychain.

use std::path::PathBuf;

use base64::Engine;
use serde::{Deserialize, Serialize};

use crate::{Error, Result};

#[derive(Clone, Serialize, Deserialize)]
pub struct Secrets {
    /// 32 random bytes, base64: the API's vault key.
    pub master_key: String,
    /// The Postgres superuser, used only to create the roles below.
    pub admin_password: String,
    /// The schema owner, used only for migrations.
    pub owner_password: String,
    /// The least-privilege role the API runs as.
    pub app_password: String,
}

impl Secrets {
    pub fn generate() -> Result<Self> {
        Ok(Self {
            master_key: base64::engine::general_purpose::STANDARD.encode(random_bytes::<32>()?),
            admin_password: random_hex(32)?,
            owner_password: random_hex(32)?,
            app_password: random_hex(32)?,
        })
    }
}

fn random_bytes<const N: usize>() -> Result<[u8; N]> {
    let mut bytes = [0u8; N];
    getrandom::fill(&mut bytes).map_err(|e| Error::new(format!("No secure randomness: {e}")))?;
    Ok(bytes)
}

pub(crate) fn random_hex(bytes: usize) -> Result<String> {
    let mut buffer = vec![0u8; bytes];
    getrandom::fill(&mut buffer).map_err(|e| Error::new(format!("No secure randomness: {e}")))?;
    Ok(buffer.iter().map(|b| format!("{b:02x}")).collect())
}

pub trait SecretStore {
    fn load(&self) -> Result<Option<Secrets>>;
    fn save(&self, secrets: &Secrets) -> Result<()>;
}

fn parse(text: &str) -> Result<Secrets> {
    serde_json::from_str(text).map_err(|e| Error::new(format!("Stored keys are unreadable: {e}")))
}

fn serialize(secrets: &Secrets) -> Result<String> {
    serde_json::to_string(secrets).map_err(|e| Error::new(e.to_string()))
}

/// The OS keychain: what the desktop app uses.
#[cfg(any(target_os = "macos", target_os = "windows"))]
pub struct Keychain {
    entry: keyring_core::Entry,
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
impl Keychain {
    /// `service` names the entry, e.g. the app's identifier.
    pub fn new(service: &str) -> Result<Self> {
        let failed = |e: keyring_core::Error| {
            Error::new(format!("The system keychain isn't available: {e}"))
        };
        #[cfg(target_os = "macos")]
        let store = apple_native_keyring_store::keychain::Store::new().map_err(failed)?;
        #[cfg(target_os = "windows")]
        let store = windows_native_keyring_store::Store::new().map_err(failed)?;
        keyring_core::set_default_store(store);
        let entry = keyring_core::Entry::new(service, "local-database").map_err(failed)?;
        Ok(Self { entry })
    }
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
impl SecretStore for Keychain {
    fn load(&self) -> Result<Option<Secrets>> {
        match self.entry.get_password() {
            Ok(text) => parse(&text).map(Some),
            Err(keyring_core::Error::NoEntry) => Ok(None),
            Err(e) => Err(Error::new(format!(
                "Couldn't read the system keychain: {e}"
            ))),
        }
    }
    fn save(&self, secrets: &Secrets) -> Result<()> {
        self.entry
            .set_password(&serialize(secrets)?)
            .map_err(|e| Error::new(format!("Couldn't save to the system keychain: {e}")))
    }
}

/// A file readable only by this user. For development and tests on
/// systems without a supported keychain; the desktop app doesn't use it.
pub struct SecretFile(pub PathBuf);

impl SecretStore for SecretFile {
    fn load(&self) -> Result<Option<Secrets>> {
        match std::fs::read_to_string(&self.0) {
            Ok(text) => parse(&text).map(Some),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(e) => Err(e.into()),
        }
    }
    fn save(&self, secrets: &Secrets) -> Result<()> {
        if let Some(parent) = self.0.parent() {
            std::fs::create_dir_all(parent)?;
        }
        Ok(crate::write_private(&self.0, &serialize(secrets)?)?)
    }
}
