# Privacy policy: Automation reel

Automation reel is a personal tool that Hassan Jan (@hassanjan.k) runs for his own accounts. It is not offered to
anyone else, and no one else signs in to it.

## What it does with Google and YouTube

It signs in to Hassan Jan's own YouTube channel with Google OAuth, using only the `youtube.upload` permission, to
upload the short videos it makes (its daily reels and showcases) to that channel. It does not read, store or change
anything else in the Google account.

## What data it keeps

- The login (a refresh token) is kept as an encrypted GitHub Actions secret in this repository, readable only by its
  workflows.
- After an upload it records the new video's id in this repository, so the same video is never uploaded twice.
- It collects no data about the people who watch the videos, and sells or shares nothing with anyone.

## Instagram and LinkedIn

The same tool posts the same videos to Hassan Jan's own Instagram and LinkedIn accounts with their official APIs. On
Instagram it reads the comments on his own posts to answer questions about them. A comment it leaves for him to answer
is listed, with the commenter's public username and words, in an issue of this repository (an Instagram comment is
public already); nothing else about commenters is kept.

## Removing access

Access can be removed at any time at https://myaccount.google.com/permissions, or by deleting the repository's
`YT_REFRESH_TOKEN` secret.

## Contact

hijani29714@gmail.com
