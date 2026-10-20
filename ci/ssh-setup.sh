#!/usr/bin/env bash
# Creates two disposable users; never run on a workstation or shared runner.
set -euo pipefail
[[ ${GITHUB_ACTIONS:-} == true || ${CLUSTERLINK_DISPOSABLE_CI:-} == true ]]
[[ $# == 1 ]]
wheel=$(realpath "$1")
sudo python3 -m venv /opt/clusterlink-ci
sudo /opt/clusterlink-ci/bin/pip install "$wheel"
sudo cp ci/target.py /opt/clusterlink-ci/target.py
sudo systemctl start ssh
# Ubuntu's AppArmor userns restriction prevents unprivileged Apptainer builds.
# This adjustment applies only to this disposable test VM.
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
ssh-keygen -q -t ed25519 -N '' -f "$HOME/.ssh/clusterlink-ci"
ssh-keyscan -H 127.0.0.1 >> "$HOME/.ssh/known_hosts"
for site in cia cib; do
  sudo useradd --create-home --shell /bin/bash "$site"
  sudo chmod 700 "/home/$site"
  sudo install -d -m 700 -o "$site" -g "$site" "/home/$site/.ssh"
  sudo install -m 600 -o "$site" -g "$site" "$HOME/.ssh/clusterlink-ci.pub" "/home/$site/.ssh/authorized_keys"
  printf 'export CONDOR_CONFIG=/home/%s/pool/condor.config\nexport PATH=/usr/bin:/usr/sbin:/bin\n' "$site" | sudo tee "/home/$site/.bashrc" >/dev/null
  printf '. ~/.bashrc\n' | sudo tee "/home/$site/.bash_profile" >/dev/null
  sudo chown "$site:$site" "/home/$site/.bashrc" "/home/$site/.bash_profile"
  sudo -u "$site" -H /opt/clusterlink-ci/bin/python /opt/clusterlink-ci/target.py
  cat >> "$HOME/.ssh/config" <<EOF
Host $site
    HostName 127.0.0.1
    User $site
    IdentityFile $HOME/.ssh/clusterlink-ci
    IdentitiesOnly yes
    StrictHostKeyChecking yes
EOF
  ssh "$site" condor_q -totals
done
chmod 600 "$HOME/.ssh/config"
