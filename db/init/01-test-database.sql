-- Runs once when the Docker volume is first initialized.
-- Separate database for the test suite (tests refuse databases not ending in "_test").
CREATE DATABASE mentor_pro_test OWNER mentor_pro_admin ENCODING 'UTF8' TEMPLATE template0;
