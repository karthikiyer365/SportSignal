-- WhoScored (Opta) player id on Big-5 player_season rows, set by action_score.link_whoscored.
-- Lets a report opened by tm_id find the player's action file
-- (action-score bucket, <league>-<season>/player_actions/<whoscored_id>.json).
-- Apply manually in SQL editor.
alter table player_season add column if not exists whoscored_id bigint;
