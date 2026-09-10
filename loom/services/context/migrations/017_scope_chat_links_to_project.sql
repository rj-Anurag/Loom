ALTER TABLE chat_links DROP CONSTRAINT IF EXISTS chat_links_chat_url_key;
ALTER TABLE chat_links DROP CONSTRAINT IF EXISTS uq_chat_links_project_url;
ALTER TABLE chat_links ADD CONSTRAINT uq_chat_links_project_url UNIQUE (project_id, chat_url);
