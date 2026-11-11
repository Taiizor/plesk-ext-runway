# ruby-hello

Minimal Rack application served by puma for Runway.

| Setting | Value |
|---|---|
| Runtime | Ruby (Plesk Ruby extension or system Ruby) |
| Build command | `bundle install` |
| Start command | `bundle exec puma -C config/puma.rb -e production` |
| Listen | TCP port or Unix socket (`RUNWAY_SOCKET`) |
| Health check path | `/healthz` |

`config/puma.rb` binds the Unix socket in `RUNWAY_SOCKET` (with `umask=0117`, so only the owner
and the web server group can connect) or `tcp://$HOST:$PORT`. Runway suggests exactly this start command when the project has a
`config/puma.rb` (the configuration file decides where puma listens). Do not add `-b` to the start
command: a command line bind replaces every bind of the configuration file. Equivalent command
lines without the configuration file:

```sh
bundle exec puma -e production -b tcp://$HOST:$PORT
bundle exec puma -e production -b "unix://$RUNWAY_SOCKET?umask=0117"
```

The build downloads gems from rubygems.org; puma's native extension needs a C compiler and
the Ruby headers (install the build dependencies on *Runway > Toolchains*). Gems are installed
into `~/.runway` of the subscription. A dependency-free variant (`ruby app.rb`, stdlib only) is
written by the domain page's **Create sample app**.
