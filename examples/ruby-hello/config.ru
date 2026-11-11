# Minimal Rack app served by puma, for testing Runway (Plesk extension).
# Build: bundle install    Start: bundle exec puma -C config/puma.rb -e production
run lambda { |env|
  body = if env["PATH_INFO"] == "/healthz"
           "ok\n"
         else
           "Hello from Rack on Ruby #{RUBY_VERSION} (pid #{Process.pid})\n"
         end
  [200, { "content-type" => "text/plain; charset=utf-8" }, [body]]
}
