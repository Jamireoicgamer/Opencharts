// SPDX-License-Identifier: AGPL-3.0-or-later
//! Starts and stops everything the desktop app runs behind its window: a
//! bundled Postgres and the frozen API, both reachable only on 127.0.0.1.
//!
//! The window code (src-tauri) and the smoke-test binary
//! (`openchart-stack`) share this, so the stack is tested without a GUI.

mod secrets;

use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::net::{Ipv4Addr, SocketAddrV4, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, ExitStatus, Stdio};
use std::thread;
use std::time::{Duration, Instant};

#[cfg(any(target_os = "macos", target_os = "windows"))]
pub use secrets::Keychain;
pub use secrets::{SecretFile, SecretStore, Secrets};

const EXE: &str = std::env::consts::EXE_SUFFIX;
const LOG_LIMIT: u64 = 5 * 1024 * 1024;
const STARTUP_TIMEOUT: Duration = Duration::from_secs(90);

/// Where the bundled programs are, and where this computer's data goes.
#[derive(Clone, Debug)]
pub struct Layout {
    /// Folder holding Postgres's `bin`, `lib` and `share`.
    pub postgres: PathBuf,
    /// The frozen API executable.
    pub api: PathBuf,
    /// The built web app (index.html and assets).
    pub web: PathBuf,
    /// This user's data: the database, logs and markers.
    pub data: PathBuf,
}

impl Layout {
    fn pg(&self, program: &str) -> PathBuf {
        self.postgres.join("bin").join(format!("{program}{EXE}"))
    }
    fn pgdata(&self) -> PathBuf {
        self.data.join("postgres")
    }
    pub fn logs(&self) -> PathBuf {
        self.data.join("logs")
    }
}

#[derive(Debug)]
pub struct Error {
    pub message: String,
    /// The log that explains it, when there is one.
    pub log: Option<PathBuf>,
}

impl Error {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
            log: None,
        }
    }
    fn with_log(message: impl Into<String>, log: PathBuf) -> Self {
        Self {
            message: message.into(),
            log: Some(log),
        }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match &self.log {
            Some(log) => write!(f, "{} (see {})", self.message, log.display()),
            None => f.write_str(&self.message),
        }
    }
}

impl std::error::Error for Error {}

impl From<io::Error> for Error {
    fn from(error: io::Error) -> Self {
        Self::new(error.to_string())
    }
}

pub type Result<T> = std::result::Result<T, Error>;

/// The running stack. Call [`Stack::stop`] before exiting.
pub struct Stack {
    layout: Layout,
    api: Child,
    api_stdin: Option<ChildStdin>,
    /// The port the API (and web app) listens on, on 127.0.0.1.
    pub port: u16,
    /// Set when no owner account exists yet: the first-run setup token.
    pub setup_token: Option<String>,
}

impl Stack {
    /// Start Postgres and the API, creating the database on first run.
    pub fn start(layout: &Layout, store: &dyn SecretStore) -> Result<Stack> {
        // Helpers run in the data folder, so relative paths would break.
        let layout = &Layout {
            postgres: plain_path(&std::path::absolute(&layout.postgres)?),
            api: plain_path(&std::path::absolute(&layout.api)?),
            web: plain_path(&std::path::absolute(&layout.web)?),
            data: plain_path(&std::path::absolute(&layout.data)?),
        };
        let logs = layout.logs();
        fs::create_dir_all(&logs)?;
        #[cfg(unix)]
        {
            // Logs and markers are this user's business only.
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&layout.data, fs::Permissions::from_mode(0o700))?;
        }
        let fresh = !layout.pgdata().join("PG_VERSION").is_file();
        let secrets = match store.load()? {
            Some(secrets) => secrets,
            None if fresh => {
                let secrets = Secrets::generate()?;
                store.save(&secrets)?;
                secrets
            }
            None => {
                return Err(Error::new(
                    "This computer has OpenChart data, but its keys are missing from the \
                     system keychain, so the data can't be opened.",
                ));
            }
        };
        if fresh {
            init_database(layout, &secrets)?;
        }
        let pg_port = start_postgres(layout)?;
        let started = start_api(layout, &secrets, pg_port);
        if started.is_err() {
            stop_postgres(layout);
        }
        started
    }

    /// The address to open in the window.
    pub fn origin(&self) -> String {
        origin(self.port)
    }

    /// Where the window should go first: setup on a fresh install.
    pub fn start_url(&self) -> String {
        match &self.setup_token {
            Some(token) => format!("{}/setup#token={token}", self.origin()),
            None => format!("{}/", self.origin()),
        }
    }

    /// Stop the API, then Postgres.
    pub fn stop(mut self) {
        // Closing its stdin tells the API to shut down cleanly.
        drop(self.api_stdin.take());
        if wait_for_exit(&mut self.api, Duration::from_secs(10)).is_none() {
            let _ = self.api.kill();
            let _ = self.api.wait();
        }
        stop_postgres(&self.layout);
    }
}

/// Turns Windows "verbatim" paths (`\\?\C:\...`), which the installed app gets
/// for its own folder, as plain `C:\...` paths. initdb runs postgres through
/// cmd.exe, which can't run a verbatim path. Network paths keep the prefix.
pub fn plain_path(path: &Path) -> PathBuf {
    let text = path.to_string_lossy();
    match text.strip_prefix(r"\\?\") {
        Some(rest) if !rest.starts_with("UNC\\") => PathBuf::from(rest),
        _ => path.to_path_buf(),
    }
}

fn origin(port: u16) -> String {
    format!("http://localhost:{port}")
}

fn init_database(layout: &Layout, secrets: &Secrets) -> Result<()> {
    let pgdata = layout.pgdata();
    let log = layout.logs().join("initdb.log");
    // A previous first run may have stopped half-way.
    if pgdata.exists() {
        fs::remove_dir_all(&pgdata)?;
    }
    let pwfile = layout.data.join(".initdb-password");
    write_private(&pwfile, &secrets.admin_password)?;
    let status = run(
        Command::new(layout.pg("initdb"))
            .arg("-D")
            .arg(&pgdata)
            .args([
                "-U",
                "postgres",
                "-A",
                "scram-sha-256",
                "-E",
                "UTF8",
                "--no-locale",
            ])
            .arg(format!("--pwfile={}", pwfile.display())),
        &log,
    );
    let _ = fs::remove_file(&pwfile);
    if !status?.success() {
        let _ = fs::remove_dir_all(&pgdata);
        return Err(Error::with_log("Couldn't create the database", log));
    }
    // Loopback only, no Unix socket, and sized for one person.
    let mut conf = OpenOptions::new()
        .append(true)
        .open(pgdata.join("postgresql.conf"))?;
    conf.write_all(
        b"\n# OpenChart desktop\n\
          listen_addresses = '127.0.0.1'\n\
          unix_socket_directories = ''\n\
          max_connections = 40\n\
          shared_buffers = 64MB\n\
          password_encryption = 'scram-sha-256'\n\
          include_if_exists = 'openchart-port.conf'\n",
    )?;
    Ok(())
}

fn start_postgres(layout: &Layout) -> Result<u16> {
    let pgdata = layout.pgdata();
    let log = layout.logs().join("postgres.log");
    // Still running after a crash? Stop it, so it picks up a fresh port.
    let status = Command::new(layout.pg("pg_ctl"))
        .arg("status")
        .arg("-D")
        .arg(&pgdata)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .no_window()
        .status()?;
    if status.success() {
        stop_postgres(layout);
    }
    let port = free_port()?;
    fs::write(
        pgdata.join("openchart-port.conf"),
        format!("port = {port}\n"),
    )?;
    rotate(&log);
    let status = run(
        Command::new(layout.pg("pg_ctl"))
            .arg("start")
            .arg("-D")
            .arg(&pgdata)
            .args(["-w", "-t", "60", "-l"])
            .arg(&log),
        &layout.logs().join("pg_ctl.log"),
    )?;
    if !status.success() {
        return Err(Error::with_log("The database didn't start", log));
    }
    Ok(port)
}

fn stop_postgres(layout: &Layout) {
    let _ = Command::new(layout.pg("pg_ctl"))
        .arg("stop")
        .arg("-D")
        .arg(layout.pgdata())
        .args(["-m", "fast", "-w", "-t", "30"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .no_window()
        .status();
}

fn database_url(role: &str, password: &str, port: u16, database: &str) -> String {
    // Passwords are hex, so they need no escaping.
    format!("postgresql+asyncpg://{role}:{password}@127.0.0.1:{port}/{database}")
}

fn api_command(layout: &Layout) -> Command {
    let mut command = Command::new(&layout.api);
    command.current_dir(&layout.data).no_window();
    // Only the settings below apply, whatever the user's environment holds.
    for (name, _) in std::env::vars_os() {
        if name
            .to_string_lossy()
            .to_ascii_uppercase()
            .starts_with("OPENCHART_")
        {
            command.env_remove(name);
        }
    }
    command
}

fn start_api(layout: &Layout, secrets: &Secrets, pg_port: u16) -> Result<Stack> {
    let log = layout.logs().join("api.log");
    rotate(&log);
    let bootstrapped = layout.data.join(".bootstrapped");
    if !bootstrapped.is_file() {
        let admin = format!(
            "postgresql://postgres:{}@127.0.0.1:{pg_port}/postgres",
            secrets.admin_password
        );
        let status = run(
            api_command(layout)
                .arg("bootstrap")
                .env("OPENCHART_BOOTSTRAP_ADMIN_URL", admin)
                .env(
                    "OPENCHART_BOOTSTRAP_OWNER_PASSWORD",
                    &secrets.owner_password,
                )
                .env("OPENCHART_BOOTSTRAP_APP_PASSWORD", &secrets.app_password),
            &log,
        )?;
        if !status.success() {
            return Err(Error::with_log("Couldn't set up the database", log));
        }
        fs::write(&bootstrapped, b"")?;
    }
    let status = run(
        api_command(layout)
            .arg("migrate")
            .env(
                "OPENCHART_MIGRATE_DATABASE_URL",
                database_url(
                    "openchart_owner",
                    &secrets.owner_password,
                    pg_port,
                    "openchart",
                ),
            )
            .env("OPENCHART_APP_ROLE", "openchart_app"),
        &log,
    )?;
    if !status.success() {
        return Err(Error::with_log("Couldn't update the database", log));
    }

    let port = free_port()?;
    let setup_token = secrets::random_hex(24)?;
    let output = append_log(&log)?;
    let mut api = api_command(layout)
        .args([
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
            "--exit-with-stdin",
        ])
        .env(
            "OPENCHART_DATABASE_URL",
            database_url("openchart_app", &secrets.app_password, pg_port, "openchart"),
        )
        .env("OPENCHART_MASTER_KEY", &secrets.master_key)
        .env("OPENCHART_PUBLIC_ORIGIN", origin(port))
        .env("OPENCHART_STATIC_DIR", &layout.web)
        .env("OPENCHART_SETUP_TOKEN", &setup_token)
        .stdin(Stdio::piped())
        .stdout(output.try_clone()?)
        .stderr(output)
        .spawn()?;
    let api_stdin = api.stdin.take();

    let deadline = Instant::now() + STARTUP_TIMEOUT;
    loop {
        if let Ok(Some(_)) = api.try_wait() {
            return Err(Error::with_log(
                "The OpenChart service stopped while starting",
                log,
            ));
        }
        if let Ok((200, _)) = get(port, "/api/health") {
            break;
        }
        if Instant::now() > deadline {
            let _ = api.kill();
            let _ = api.wait();
            return Err(Error::with_log(
                "The OpenChart service didn't start in time",
                log,
            ));
        }
        thread::sleep(Duration::from_millis(150));
    }
    let needs_setup = match get(port, "/api/setup/status") {
        Ok((200, body)) => serde_json::from_str::<serde_json::Value>(&body)
            .ok()
            .and_then(|v| v.get("needs_setup").and_then(|n| n.as_bool()))
            .unwrap_or(false),
        _ => false,
    };
    Ok(Stack {
        layout: layout.clone(),
        api,
        api_stdin,
        port,
        setup_token: needs_setup.then_some(setup_token),
    })
}

/// A plain HTTP GET to the local API: (status, body).
pub fn get(port: u16, path: &str) -> io::Result<(u16, String)> {
    let address = SocketAddrV4::new(Ipv4Addr::LOCALHOST, port);
    let mut stream = TcpStream::connect_timeout(&address.into(), Duration::from_secs(2))?;
    stream.set_read_timeout(Some(Duration::from_secs(5)))?;
    write!(
        stream,
        "GET {path} HTTP/1.1\r\nHost: localhost:{port}\r\nConnection: close\r\n\r\n"
    )?;
    let mut response = String::new();
    stream.read_to_string(&mut response)?;
    let status = response
        .split(' ')
        .nth(1)
        .and_then(|code| code.parse().ok())
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "not an HTTP response"))?;
    let body = response
        .split_once("\r\n\r\n")
        .map(|(_, b)| b.to_owned())
        .unwrap_or_default();
    Ok((status, body))
}

fn free_port() -> io::Result<u16> {
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))?;
    Ok(listener.local_addr()?.port())
}

fn wait_for_exit(child: &mut Child, timeout: Duration) -> Option<ExitStatus> {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if let Ok(Some(status)) = child.try_wait() {
            return Some(status);
        }
        thread::sleep(Duration::from_millis(100));
    }
    None
}

/// Run to completion with output appended to `log`.
fn run(command: &mut Command, log: &Path) -> Result<ExitStatus> {
    let output = append_log(log)?;
    let status = command
        .stdin(Stdio::null())
        .stdout(output.try_clone()?)
        .stderr(output)
        .no_window()
        .status()
        .map_err(|e| Error::new(format!("Couldn't run {:?}: {e}", command.get_program())))?;
    Ok(status)
}

fn append_log(path: &Path) -> io::Result<File> {
    OpenOptions::new().create(true).append(true).open(path)
}

/// Keep logs from growing without limit: one previous copy is kept.
fn rotate(path: &Path) {
    if fs::metadata(path).is_ok_and(|m| m.len() > LOG_LIMIT) {
        let _ = fs::rename(path, path.with_extension("log.1"));
    }
}

/// Write a file only this user can read.
pub(crate) fn write_private(path: &Path, contents: &str) -> io::Result<()> {
    let mut options = OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options.open(path)?.write_all(contents.as_bytes())
}

trait NoWindow {
    /// On Windows, don't flash a console window for each helper process.
    fn no_window(&mut self) -> &mut Self;
}

impl NoWindow for Command {
    #[cfg(windows)]
    fn no_window(&mut self) -> &mut Self {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        self.creation_flags(CREATE_NO_WINDOW)
    }
    #[cfg(not(windows))]
    fn no_window(&mut self) -> &mut Self {
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn verbatim_windows_paths_become_plain() {
        let cases = [
            (
                r"\\?\C:\Users\Jamie\AppData\Local\OpenChart\postgres",
                r"C:\Users\Jamie\AppData\Local\OpenChart\postgres",
            ),
            (r"C:\Program Files\OpenChart", r"C:\Program Files\OpenChart"),
            (
                "/Applications/OpenChart.app/Contents/Resources",
                "/Applications/OpenChart.app/Contents/Resources",
            ),
            (
                r"\\?\UNC\server\share\OpenChart",
                r"\\?\UNC\server\share\OpenChart",
            ),
        ];
        for (given, expected) in cases {
            assert_eq!(
                plain_path(Path::new(given)),
                PathBuf::from(expected),
                "{given}"
            );
        }
    }
}
