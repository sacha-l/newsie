#!/bin/sh
# This repo belongs to github.com/sacha-l (Sacha Lansky, account id 23283108).
# sacha@users.noreply.github.com belongs to github.com/sacha (a different person).
# GitHub attributes commits to whichever account owns the email, so that
# address must never be used here.
set -eu

ALLOWED="23283108+sacha-l@users.noreply.github.com"
MERGE_BOT="noreply@github.com"

die() {
  echo "commit-identity: $*" >&2
  exit 1
}

lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

check_email() {
  role=$1
  email=$(lower "$2")
  if [ "$email" = "$(lower "$ALLOWED")" ] || [ "$email" = "$MERGE_BOT" ]; then
    return 0
  fi
  case "$email" in
    *@users.noreply.github.com)
      die "$role email $email is not this account. Use $ALLOWED"
      ;;
  esac
}

extract_email() {
  printf '%s\n' "$1" | sed -n 's/.*<\([^>]*\)>.*/\1/p'
}

mode=${1:---ident}

if [ "$mode" = "--history" ]; then
  tmp=$(mktemp)
  trap 'rm -f "$tmp"' EXIT
  git log --format='%ae%n%ce' HEAD >"$tmp"
  while IFS= read -r email; do
    [ -n "$email" ] || continue
    check_email "history" "$email"
  done <"$tmp"
  exit 0
fi

if [ "$mode" = "--ident" ]; then
  author=$(extract_email "$(git var GIT_AUTHOR_IDENT)")
  committer=$(extract_email "$(git var GIT_COMMITTER_IDENT)")
  [ -n "$author" ] || die "could not read author email"
  [ -n "$committer" ] || die "could not read committer email"
  check_email "author" "$author"
  check_email "committer" "$committer"
  exit 0
fi

die "usage: check_commit_email.sh [--ident|--history]"
