require 'sinatra'
require 'sinatra/reloader' if development?
require 'sinatra/cookies'
require 'rexml/document'
require 'webrick'
require 'pp'
require 'webrick/https'
require 'openssl'
require 'logger'
require 'thread'

require 'bootstrap.rb'
require 'resource.rb'
require 'remote.rb'
require 'fenceagent.rb'
require 'cluster.rb'
require 'config.rb'
require 'pcs.rb'
require 'auth.rb'
require 'wizard.rb'
require 'cfgsync.rb'
require 'permissions.rb'

Dir["wizards/*.rb"].each {|file| require file}

use Rack::CommonLogger

begin
  secret = File.read(COOKIE_FILE)
rescue Errno::ENOENT
  secret = SecureRandom.hex(30)
  File.open(COOKIE_FILE, 'w', 0700) {|f| f.write(secret)}
end

use Rack::Session::Cookie,
  :expire_after => 60 * 60,
  :secret => secret,
  :secure => true, # only send over HTTPS
  :httponly => true # don't provide to javascript

#use Rack::SSL

if development?
  Dir["wizards/*.rb"].each {|file| also_reload file}
  also_reload 'resource.rb'
  also_reload 'remote.rb'
  also_reload 'fenceagent.rb'
  also_reload 'cluster.rb'
  also_reload 'config.rb'
  also_reload 'pcs.rb'
  also_reload 'auth.rb'
  also_reload 'wizard.rb'
  also_reload 'cfgsync.rb'
end

before do
  if request.path != '/login' and not request.path == "/logout" and not request.path == '/remote/auth'
    protected! 
  end
  $cluster_name = get_cluster_name()
  @errorval = session[:errorval]
  @error = session[:error]
  session[:errorval] = nil
  session[:error] = nil
end

configure do
  DISABLE_GUI = false
  PCS = get_pcs_path(File.expand_path(File.dirname(__FILE__)))
  logger = File.open("/var/log/pcsd/pcsd.log", "a+", 0600)
  STDOUT.reopen(logger)
  STDERR.reopen(logger)
  STDOUT.sync = true
  STDERR.sync = true
  $logger = configure_logger('/var/log/pcsd/pcsd.log')
  $semaphore_cfgsync = Mutex.new
end

set :logging, true
set :run, false

$thread_cfgsync = Thread.new {
  while true
    $semaphore_cfgsync.synchronize {
      $logger.debug('Config files sync thread started')
      if Cfgsync::ConfigSyncControl.sync_thread_allowed?()
        begin
          # do not sync if this host is not in a cluster
          cluster_name = get_cluster_name()
          if cluster_name and !cluster_name.empty?()
            $logger.debug('Config files sync thread fetching')
            fetcher = Cfgsync::ConfigFetcher.new(
              Cfgsync::get_cfg_classes(), get_corosync_nodes(),
              cluster_name, SUPERUSER
            )
            cfgs_to_save, _ = fetcher.fetch()
            cfgs_to_save.each { |cfg_to_save|
              cfg_to_save.save()
            }
          end
        rescue => e
          $logger.warn("Config files sync thread exception: #{e}")
        end
      end
      $logger.debug('Config files sync thread finished')
    }
    sleep(Cfgsync::ConfigSyncControl.sync_thread_interval())
  end
}

helpers do
  def protected!
    PCSAuth.loginByToken(session, cookies) if not PCSAuth.isLoggedIn(session)
    if not PCSAuth.isLoggedIn(session)
      # If we're on /managec/<cluster_name>/main we redirect
      match_expr = "/managec/(.*)/(.*)"
      mymatch = request.path.match(match_expr)
      on_managec_main = false
      if mymatch and mymatch.length >= 3 and mymatch[2] == "main"
        on_managec_main = true
      end

      if request.path.start_with?('/remote') or (request.path.match(match_expr) and not on_managec_main) or '/run_pcs' == request.path or 
        '/clusters_overview' == request.path
	$logger.info "ERROR: Request without authentication"
	halt [401, '{"notauthorized":"true"}']
      else
	session[:pre_login_path] = request.path
	redirect '/login'
      end
    end
  end

  def setup
    @nodes_online, @nodes_offline = get_nodes()
    @nodes = {}
    @nodes_online.each do |i|
      @nodes[i]  = Node.new(i, i, i, true)
    end
    @nodes_offline.each do |i|
      @nodes[i]  = Node.new(i, i, i, false)
    end

    if @nodes_online.length == 0
      @pcs_node_offline = true
    end

    if params[:node]
      @cur_node = @nodes[params[:node]]
      if not @cur_node
	@cur_node = @nodes.values[0]
      end
    else
      @cur_node = @nodes.values[0]
    end

    if @nodes.length != 0
      @loc_dep_allow, @loc_dep_disallow = getLocationDeps(session, @cur_node)
    end
    @nodes = @nodes_online.concat(@nodes_offline)
  end

  def getParamList(params)
    param_line = []
    meta_options = []
    params.each { |param, val|
      if param.start_with?("_res_paramne_") or (param.start_with?("_res_paramempty_") and val != "")
        myparam = param.sub(/^_res_paramne_/,"").sub(/^_res_paramempty_/,"")
        param_line << "#{myparam}=#{val}"
      end
      if param == "disabled"
        meta_options << "meta target-role=Stopped"
      end
    }
    return param_line + meta_options
  end
end

get '/remote/?:command?' do
  return remote(params, request, session)
end

post '/remote/?:command?' do
  return remote(params, request, session)
end

post '/run_pcs' do
  command = params['command'] || '{}'
  std_in = params['stdin'] || nil
  begin
    command_decoded = JSON.parse(command)
  rescue JSON::ParserError
    result = {
      'status' => 'error',
      'data' => {},
    }
    return JSON.pretty_generate(result)
  end
  # do not reveal potentialy sensitive information
  command_decoded.delete('--debug')

  allowed_commands = {
    ['cluster', 'auth', '...'] => {
      'only_superuser' => false,
      'permissions' => nil,
    },
    # runs on the local node, check permissions
    ['cluster', 'corosync'] => {
      'only_superuser' => false,
      'permissions' => Permissions::READ,
    },
    # runs on a remote node which checks permissions by itself
    ['cluster', 'corosync', '...'] => {
      'only_superuser' => false,
      'permissions' => nil,
    },
    ['cluster', 'destroy', '...'] => {
      'only_superuser' => true,
      'permissions' => nil,
    },
    # runs on the local node, check permissions
    ['cluster', 'disable'] => {
      'only_superuser' => false,
      'permissions' => Permissions::WRITE,
    },
    # runs on a remote node which checks permissions by itself
    ['cluster', 'disable', '...'] => {
      'only_superuser' => false,
      'permissions' => nil,
    },
    # runs on the local node, check permissions
    ['cluster', 'enable'] => {
      'only_superuser' => false,
      'permissions' => Permissions::WRITE,
    },
    # runs on a remote node which checks permissions by itself
    ['cluster', 'enable', '...'] => {
      'only_superuser' => false,
      'permissions' => nil,
    },
    ['cluster', 'node', '...'] => {
      'only_superuser' => true,
      'permissions' => nil,
    },
    ['cluster', 'pcsd-status', '...'] => {
      'only_superuser' => false,
      'permissions' => nil,
    },
    ['cluster', 'setup', '...'] => {
      'only_superuser' => true,
      'permissions' => nil,
    },
    # runs on the local node, check permissions
    ['cluster', 'start'] => {
      'only_superuser' => false,
      'permissions' => Permissions::WRITE,
    },
    # runs on a remote node which checks permissions by itself
    ['cluster', 'start', '...'] => {
      'only_superuser' => false,
      'permissions' => nil,
    },
    # runs on the local node, check permissions
    ['cluster', 'stop'] => {
      'only_superuser' => false,
      'permissions' => Permissions::WRITE,
    },
    # runs on a remote node which checks permissions by itself
    ['cluster', 'stop', '...'] => {
      'only_superuser' => false,
      'permissions' => nil,
    },
    ['config', 'restore', '...'] => {
      'only_superuser' => true,
      'permissions' => nil,
    },
    ['pcsd', 'sync-certificates', '...'] => {
      'only_superuser' => true,
      'permissions' => nil,
    },
    ['status', 'nodes', 'corosync-id', '...'] => {
      'only_superuser' => false,
      'permissions' => Permissions::READ,
    },
    ['status', 'nodes', 'pacemaker-id', '...'] => {
      'only_superuser' => false,
      'permissions' => Permissions::READ,
    },
    ['status', 'pcsd', '...'] => {
      'only_superuser' => false,
      'permissions' => nil,
    },
  }
  allowed = false
  command_settings = {}
  allowed_commands.each { |cmd, cmd_settings|
    if command_decoded == cmd \
      or \
      (cmd[-1] == '...' and cmd[0..-2] == command_decoded[0..(cmd.length - 2)])
      then
        allowed = true
        command_settings = cmd_settings
        break
    end
  }
  if !allowed
    result = {
      'status' => 'bad_command',
      'data' => {},
    }
    return JSON.pretty_generate(result)
  end

  if command_settings['only_superuser']
    if not allowed_for_superuser(session)
      return 403, 'Permission denied'
    end
  end
  if command_settings['permissions']
    if not allowed_for_local_cluster(session, command_settings['permissions'])
      return 403, 'Permission denied'
    end
  end

  options = {}
  options['stdin'] = std_in if std_in
  std_out, std_err, retval = run_cmd_options(
    session, options, PCS, *command_decoded
  )
  result = {
    'status' => 'ok',
    'data' => {
      'stdout' => std_out.join(""),
      'stderr' => std_err.join(""),
      'code' => retval,
    },
  }
  return JSON.pretty_generate(result)
end

if not DISABLE_GUI
  get('/login'){ erb :login, :layout => :main }

  get '/logout' do 
    session.clear
    erb :login, :layout => :main
  end

  post '/login' do
    if PCSAuth.loginByPassword(session, params['username'], params['password'])
      # Temporarily ignore pre_login_path until we come up with a list of valid
      # paths to redirect to (to prevent status_all issues)
      #    if session["pre_login_path"]
      #      plp = session["pre_login_path"]
      #      session.delete("pre_login_path")
      #      pp "Pre Login Path: " + plp
      #      if plp == "" or plp == "/"
      #      	plp = '/manage'
      #      end
      #      redirect plp
      #    else
      redirect '/manage'
      #    end
    else
      session["bad_login_name"] = params['username']
      redirect '/login?badlogin=1'
    end
  end

  post '/fencerm' do
    if not allowed_for_local_cluster(session, Permissions::WRITE)
      return 403, 'Permission denied'
    end
    params.each { |k,v|
      if k.index("resid-") == 0
        run_cmd(session, PCS, "resource", "delete", k.gsub("resid-",""))
      end
    }
    redirect "/fencedevices/"
  end

  get '/configure/?:page?' do
    if not allowed_for_local_cluster(session, Permissions::READ)
      return 403, 'Permission denied'
    end
    @config_options = getConfigOptions(params[:page])
    @configuremenuclass = "class=\"active\""
    erb :configure, :layout => :main
  end

  get '/fencedevices2/?:fencedevice?' do
    if not allowed_for_local_cluster(session, Permissions::READ)
      return 403, 'Permission denied'
    end
    @resources, @groups = getResourcesGroups(session, true)
    pp @resources

    if @resources.length == 0
      @cur_resource = nil
      @resource_agents = getFenceAgents()
    else
      @cur_resource = @resources[0]
      if params[:fencedevice]
        @resources.each do |fd|
          if fd.id == params[:fencedevice]
            @cur_resource = fd
            break
          end
        end
      end
      @cur_resource.options = getResourceOptions(session, @cur_resource.id)
      @resource_agents = getFenceAgents(@cur_resource.agentname)
    end
    erb :fencedevices, :layout => :main
  end

  ['/resources2/?:resource?', '/resource_list/?:resource?'].each do |path|
    get path do
      if not allowed_for_local_cluster(session, Permissions::READ)
        return 403, 'Permission denied'
      end
      @load_data = true
      @resources, @groups = getResourcesGroups(session)
      @resourcemenuclass = "class=\"active\""

      if @resources.length == 0
        @cur_resource = nil
        @resource_agents = getResourceAgents(session)
      else
        @cur_resource = @resources[0]
        @cur_resource.options = getResourceOptions(session, @cur_resource.id)
        if params[:resource]
          @resources.each do |r|
            if r.id == params[:resource]
              @cur_resource = r
              @cur_resource.options = getResourceOptions(session, r.id)
              break
            end
          end
        end
        @resource_agents = getResourceAgents(
          session, @cur_resource.agentname
        )
        @ord_dep_before, @ord_dep_after  = getOrderingConstraints(session, @cur_resource.id)
        @colo_dep_together, @colo_dep_apart = getColocationConstraints(session, @cur_resource.id)
        @enabled_nodes, @disabled_nodes = getLocationConstraints(session, @cur_resource.id)
      end

      @nodes_online, @nodes_offline = get_nodes

      if path.start_with? '/resource_list'
        erb :_resource_list
      else
        erb :resource, :layout => :main
      end
    end
  end

  get '/nodes/?:node?' do
    if not allowed_for_local_cluster(session, Permissions::READ)
      return 403, 'Permission denied'
    end
    setup()
    @load_data = true
    #  @nodemenuclass = "class=\"active\""
    @resources, @groups = getResourcesGroups(session)
    #  @resources_running = []
    #  @resources.each { |r|
    #    @cur_node && r.nodes && r.nodes.each {|n|
    #      if n.name == @cur_node.id
    #	@resources_running << r
    #      end
    #    }
    #  }
    @resource_agents = getResourceAgents(session)
    @stonith_agents = getFenceAgents()
    #  @nodes = @nodes.sort_by{|k,v|k}
    erb :nodes, :layout => :main
  end

  get '/manage/?' do
    @manage = true
    erb :manage, :layout => :main
  end

  get '/clusters_overview' do
    clusters_overview(params, request, session)
  end

  get '/managec/:cluster/main' do
    @cluster_name = params[:cluster]
    #  @resources, @groups = getResourcesGroups(session)
    @load_data = true
    pcs_config = PCSConfig.new(Cfgsync::PcsdSettings.from_file('').text())
    @clusters = pcs_config.clusters
    @resources = []
    @groups = []
    @nodes = get_cluster_nodes(params[:cluster])
    if @nodes == []
      redirect '/manage/?error=badclustername&errorval=' + params[:cluster] + '#manage'
    end
    @resource_agents = get_resource_agents_avail(session)
    @stonith_agents = get_stonith_agents_avail(session)
    @config_options = getConfigOptions2(session, @cluster_name)

    erb :nodes, :layout => :main
  end

  get '/managec/:cluster/status_all' do
    status_all(params, request, session, get_cluster_nodes(params[:cluster]))
  end

  get '/managec/:cluster/cluster_status' do
    cluster_status(params, request, session, params[:cluster])
  end

  get '/managec/:cluster/overview_cluster' do
    overview_cluster(params, request, session)
  end

  get '/managec/:cluster/?*' do
    raw_data = request.env["rack.input"].read
    if params[:cluster]
      send_cluster_request_with_token(
        session, params[:cluster], "/" + params[:splat].join("/"), false, params,
        true, raw_data
      )
    end
  end

  post '/managec/:cluster/?*' do
    raw_data = request.env["rack.input"].read
    if params[:cluster]
      request = "/" + params[:splat].join("/")
      code, out = send_cluster_request_with_token(
        session, params[:cluster], request, true, params, true, raw_data
      )

      # backward compatibility layer BEGIN
      # This code correctly remove constraints on pcs/pcsd version 0.9.137 and older
      redirection = {
          "/remove_constraint_remote" => "/resource_cmd/rm_constraint",
          "/remove_constraint_rule_remote" => "/resource_cmd/rm_constraint_rule"
      }
      if code == 404 and redirection.key?(request)
        code, out = send_cluster_request_with_token(
          session, params[:cluster], redirection[request], true, params, false,
          raw_data
        )
      end
      # bcl END
      return code, out
    end
  end

  get '/manage/:node/?*' do
    if params[:node]
      return send_request_with_token(
        session, params[:node], params[:splat].join("/"), false, {}, false
      )
    end
  end

  post '/manage/existingcluster' do
    pcs_config = PCSConfig.new(Cfgsync::PcsdSettings.from_file('').text())
    node = params['node-name']
    code, result = send_request_with_token(
      session, node, 'status', false, {}, true, nil, 30, {}, SUPERUSER
    )
    status = JSON.parse(result)
    if status.has_key?("corosync_offline") and
      status.has_key?("corosync_online") then
      nodes = status["corosync_offline"] + status["corosync_online"]

      if status["cluster_name"] == ""
        session[:error] = "noname"
        session[:errorval] = node
        redirect '/manage'
      end

      if pcs_config.is_cluster_name_in_use(status["cluster_name"])
        session[:error] = "duplicatename"
        session[:errorval] = status["cluster_name"]
        redirect '/manage'
      end

      # auth begin
      retval, out = send_request_with_token(
        session, node, '/get_cluster_tokens', false, {}, true, nil, 30, {},
        SUPERUSER
      )
      if retval == 404 # backward compatibility layer
        session[:error] = "authimposible"
      else
        if retval != 200
          session[:error] = "cannotgettokens"
          session[:errorval] = status["cluster_name"]
          redirect '/manage'
        end
        begin
          new_tokens = JSON.parse(out)
        rescue
          session[:error] = "cannotgettokens"
          session[:errorval] = status["cluster_name"]
          redirect '/manage'
        end

        sync_config = Cfgsync::PcsdTokens.from_file('')
        pushed, _ = Cfgsync::save_sync_new_tokens(
          sync_config, new_tokens, get_corosync_nodes(), $cluster_name
        )
        if not pushed
          session[:error] = "configversionsconflict"
          session[:errorval] = sync_config.class.name
          redirect '/manage'
        end
      end
      #auth end

      pcs_config.clusters << Cluster.new(status["cluster_name"], nodes)

      sync_config = Cfgsync::PcsdSettings.from_text(pcs_config.text())
      pushed, _ = Cfgsync::save_sync_new_version(
        sync_config, get_corosync_nodes(), $cluster_name, true
      )
      if not pushed
        session[:error] = 'configversionsconflict'
        session[:errorval] = sync_config.class.name
      end
      redirect '/manage'
    else
      redirect '/manage/?error=notauthorized#manage'
    end
  end

  post '/manage/newcluster' do
    if not allowed_for_superuser(session)
      session[:error] = "permissiondenied"
      redirect '/manage'
    end

    pcs_config = PCSConfig.new(Cfgsync::PcsdSettings.from_file('').text())
    @manage = true
    @cluster_name = params[:clustername]
    @nodes = []
    nodes_with_indexes = []
    @nodes_rrp = []
    options = {}
    params.each {|k,v|
      if k.start_with?("node-") and v != ""
        @nodes << v
        nodes_with_indexes << [k[5..-1].to_i, v]
        if params.has_key?("ring1-" + k) and params["ring1-" + k] != ""
          @nodes_rrp << v + "," + params["ring1-" + k]
        else
          @nodes_rrp << v
        end
      end
      if k.start_with?("config-") and v != ""
        options[k.sub("config-","")] = v
      end
    }
    if pcs_config.is_cluster_name_in_use(@cluster_name)
      session[:error] = "duplicatename"
      session[:errorval] = @cluster_name
      redirect '/manage'
    end

    @nodes.each {|n|
      if pcs_config.is_node_in_use(n)
        session[:error] = "duplicatenodename"
        session[:errorval] = n
        redirect '/manage'
      end
    }

    # firstly we need to authenticate nodes to each other
    tokens = add_prefix_to_keys(get_tokens_of_nodes(@nodes), "node:")
    @nodes.each {|n|
      retval, out = send_request_with_token(
        session, n, "/save_tokens", true, tokens
      )
      if retval == 404 # backward compatibility layer
        session[:error] = "authimposible"
        break
      elsif retval != 200
        session[:error] = "cannotsavetokens"
        session[:errorval] = n
        redirect '/manage'
      end
    }

    # the first node from the form is the source of config files
    node_to_send_to = nodes_with_indexes.sort[0][1]
    $logger.info(
      "Sending setup cluster request for: #{@cluster_name} to: #{node_to_send_to}"
    )
    code,out = send_request_with_token(
      session,
      node_to_send_to,
      'setup_cluster',
      true,
      {
        :clustername => @cluster_name,
        :nodes => @nodes_rrp.join(';'),
        :options => options.to_json
      },
      true,
      nil,
      60
    )

    if code == 200
      pushed = false
      2.times {
        # Add the new cluster to config and publish the config.
        # If this host is a node of the cluster, some other node may send its
        # own PcsdSettings.  To handle it we just need to reload the config, as
        # we are waiting for the request to finish, so no locking is needed.
        # If we are in a different cluster we just try twice to update the
        # config, dealing with any updates in between.
        pcs_config = PCSConfig.new(Cfgsync::PcsdSettings.from_file('').text())
        pcs_config.clusters << Cluster.new(@cluster_name, @nodes)
        sync_config = Cfgsync::PcsdSettings.from_text(pcs_config.text())
        pushed, _ = Cfgsync::save_sync_new_version(
          sync_config, get_corosync_nodes(), $cluster_name, true
        )
        break if pushed
      }
      if not pushed
        session[:error] = 'configversionsconflict'
        session[:errorval] = Cfgsync::PcsdSettings.name
      end
    else
      session[:error] = "unabletocreate"
      session[:errorval] = out
    end

    redirect '/manage'
  end

  post '/manage/removecluster' do
    pcs_config = PCSConfig.new(Cfgsync::PcsdSettings.from_file('').text())
    params.each { |k,v|
      if k.start_with?("clusterid-")
        pcs_config.remove_cluster(k.sub("clusterid-",""))
      end
    }
    sync_config = Cfgsync::PcsdSettings.from_text(pcs_config.text())
    pushed, _ = Cfgsync::save_sync_new_version(
      sync_config, get_corosync_nodes(), $cluster_name, true
    )
    if not pushed
      session[:error] = 'configversionsconflict'
      session[:errorval] = sync_config.class.name
    end
    # do not reload nor redirect as that's done in js which called this
  end

  get '/' do
    $logger.info "Redirecting '/'...\n"
    redirect '/manage'
  end

  get '/wizards/?:wizard?' do
    return wizard(params, request, params[:wizard])
  end

  post '/wizards/?:wizard?' do
    return wizard(params, request, params[:wizard])
  end

  get '*' do
    $logger.debug "Bad URL"
    $logger.debug params[:splat]
    $logger.info "Redirecting '*'...\n"
    redirect '/manage'
    redirect "Bad URL"
    call(env.merge("PATH_INFO" => '/nodes'))
  end
else
  get '*' do
    $logger.debug "ERROR: GUI Disabled, Bad URL"
    $logger.debug params[:splat]
    $logger.info "Redirecting '*'...\n"
    return "PCSD GUI is disabled"
  end

end

def getLocationDeps(session, cur_node)
  out, stderror, retval = run_cmd(
    session, PCS, "constraint", "location", "show", "nodes", cur_node.id
  )
  deps_allow = []
  deps_disallow = []
  allowed = false
  disallowed = false
  out.each {|line|
    line = line.strip
    next if line == "Location Constraints:" or line.match(/^Node:/)

    if line == "Allowed to run:"
      allowed = true
      next
    elsif line == "Not allowed to run:"
      disallowed = true
      next
    end

    if disallowed == true
      deps_disallow << line.sub(/ .*/,"")
    elsif allowed == true
      deps_allow << line.sub(/ .*/,"")
    end
  }  
  [deps_allow, deps_disallow]
end

def getConfigOptions2(session, cluster_name, username=nil)
  config_options = {}
  general_page = []
#  general_page << ConfigOption.new("Cluster Delay Time", "cluster-delay",  "int", 4, "Seconds") 
#  general_page << ConfigOption.new("Batch Limit", "cdt",  "int", 4) 
#  general_page << ConfigOption.new("Default Action Timeout", "cdt",  "int", 4, "Seconds") 
#  general_page << ConfigOption.new("During timeout should cluster stop all active resources", "res_stop", "radio", "4", "", ["Yes","No"])

#  general_page << ConfigOption.new("PE Error Storage", "res_stop", "radio", "4", "", ["Yes","No"])
#  general_page << ConfigOption.new("PE Warning Storage", "res_stop", "radio", "4", "", ["Yes","No"])
#  general_page << ConfigOption.new("PE Input Storage", "res_stop", "radio", "4", "", ["Yes","No"])
  config_options["general"] = general_page

  pacemaker_page = []
  pacemaker_page << ConfigOption.new("Batch Limit", "batch-limit",  "int", 4, "jobs", {},  'The number of jobs that pacemaker is allowed to execute in parallel. The "correct" value will depend on the speed and load of your network and cluster nodes.')
  pacemaker_page << ConfigOption.new("No Quorum Policy", "no-quorum-policy",  "dropdown","" ,"", {"ignore" => "Ignore","freeze" => "Freeze", "stop" => "Stop", "suicide" => "Suicide"}, 'What to do when the cluster does not have quorum. Allowed values:
  * ignore - continue all resource management
  * freeze - continue resource management, but don\'t recover resources from nodes not in the affected partition
  * stop - stop all resources in the affected cluster partition
  * suicide - fence all nodes in the affected cluster partition')
  pacemaker_page << ConfigOption.new("Symmetric", "symmetric-cluster", "check",nil ,nil,nil,'Can all resources run on any node by default?')
  pacemaker_page << ConfigOption.new("Stonith Enabled", "stonith-enabled", "check",nil,nil,nil,'Should failed nodes and nodes with resources that can\'t be stopped be shot? If you value your data, set up a STONITH device and enable this.
If checked, the cluster will refuse to start resources unless one or more STONITH resources have been configured also.')
  pacemaker_page << ConfigOption.new("Stonith Action", "stonith-action",  "dropdown","" ,"", {"reboot" => "Reboot","off" => "Off", "poweroff" => "Poweroff"},'Action to send to STONITH device. Allowed values: reboot, off. The value poweroff is also allowed, but is only used for legacy devices.') 
  pacemaker_page << ConfigOption.new("Cluster Delay", "cluster-delay",  "int", 4,nil,nil,'Round trip delay over the network (excluding action execution). The "correct" value will depend on the speed and load of your network and cluster nodes.') 
  pacemaker_page << ConfigOption.new("Stop Orphan Resources", "stop-orphan-resources", "check",nil,nil,nil,'Should deleted resources be stopped?')
  pacemaker_page << ConfigOption.new("Stop Orphan Actions", "stop-orphan-actions", "check",nil,nil,nil,'Should deleted actions be cancelled?'
                                    )
  pacemaker_page << ConfigOption.new("Start Failure is Fatal", "start-failure-is-fatal", "check",nil,nil,nil,'When unchecked, the cluster will instead use the resource\'s failcount and value for resource-failure-stickiness.')
  pacemaker_page << ConfigOption.new("PE Error Storage", "pe-error-series-max", "int", "4",nil,nil,'The number of policy engine (PE) inputs resulting in ERRORs to save. Used when reporting problems.')
  pacemaker_page << ConfigOption.new("PE Warning Storage", "pe-warn-series-max", "int", "4",nil,nil,'The number of PE inputs resulting in WARNINGs to save. Used when reporting problems.')
  pacemaker_page << ConfigOption.new("PE Input Storage", "pe-input-series-max", "int", "4",nil,nil,'The number of "normal" PE inputs to save. Used when reporting problems.')
  pacemaker_page << ConfigOption.new("Enable ACLs", "enable-acl", "check", nil,nil,nil,'Should pacemaker use ACLs to determine access to cluster')
  config_options["pacemaker"] = pacemaker_page

  allconfigoptions = []
  config_options.each { |i,k| k.each { |j| allconfigoptions << j } }
  ConfigOption.getDefaultValues(allconfigoptions)
  ConfigOption.loadValues(session, allconfigoptions, cluster_name, nil, username)
  return config_options
end

def getConfigOptions(page="general")
  config_options = []
  case page
  when "general", nil
    cg1 = []
    cg1 << ConfigOption.new("Cluster Delay Time", "cdt",  "int", 4, "Seconds") 
    cg1 << ConfigOption.new("Batch Limit", "cdt",  "int", 4) 
    cg1 << ConfigOption.new("Default Action Timeout", "cdt",  "int", 4, "Seconds") 
    cg2 = []
    cg2 << ConfigOption.new("During timeout should cluster stop all active resources", "res_stop", "radio", "4", "", ["Yes","No"])

    cg3 = []
    cg3 << ConfigOption.new("PE Error Storage", "res_stop", "radio", "4", "", ["Yes","No"])
    cg3 << ConfigOption.new("PE Warning Storage", "res_stop", "radio", "4", "", ["Yes","No"])
    cg3 << ConfigOption.new("PE Input Storage", "res_stop", "radio", "4", "", ["Yes","No"])

    config_options << cg1
    config_options << cg2
    config_options << cg3
  when "pacemaker"
    cg1 = []
    cg1 << ConfigOption.new("Batch Limit", "batch-limit",  "int", 4, "jobs") 
    cg1 << ConfigOption.new("No Quorum Policy", "no-quorum-policy",  "dropdown","" ,"", {"ignore" => "Ignore","freeze" => "Freeze", "stop" => "Stop", "suicide" => "Suicide"}) 
    cg1 << ConfigOption.new("Symmetric", "symmetric-cluster", "check")
    cg2 = []
    cg2 << ConfigOption.new("Stonith Enabled", "stonith-enabled", "check")
    cg2 << ConfigOption.new("Stonith Action", "stonith-action",  "dropdown","" ,"", {"reboot" => "Reboot","poweroff" => "Poweroff"}) 
    cg3 = []
    cg3 << ConfigOption.new("Cluster Delay", "cluster-delay",  "int", 4) 
    cg3 << ConfigOption.new("Stop Orphan Resources", "stop-orphan-resources", "check")
    cg3 << ConfigOption.new("Stop Orphan Actions", "stop-orphan-actions", "check")
    cg3 << ConfigOption.new("Start Failure is Fatal", "start-failure-is-fatal", "check")
    cg3 << ConfigOption.new("PE Error Storage", "pe-error-series-max", "int", "4")
    cg3 << ConfigOption.new("PE Warning Storage", "pe-warn-series-max", "int", "4")
    cg3 << ConfigOption.new("PE Input Storage", "pe-input-series-max", "int", "4")

    config_options << cg1
    config_options << cg2
    config_options << cg3
  end

  allconfigoptions = []
  config_options.each { |i| i.each { |j| allconfigoptions << j } }
  ConfigOption.getDefaultValues(allconfigoptions)
  return config_options
end

class Node
  attr_accessor :active, :id, :name, :hostname

  def initialize(id=nil, name=nil, hostname=nil, active=nil)
    @id, @name, @hostname, @active = id, name, hostname, active
  end
end


class ConfigOption
  attr_accessor :name, :configname, :type, :size, :units, :options, :default, :value, :desc
  def initialize(name, configname, type="str", size = 10, units = "", options = [], desc = "")
    @name = name
    @configname = configname
    @type = type
    @size = size
    @units = units
    @options = options
    @desc = desc
  end

  def self.loadValues(session, cos, cluster_name, node_list=nil, username=nil)
    if node_list
      code, output = send_nodes_request_with_token(
        session, node_list, "get_cib", false, {}, true, nil, username
      )
    else
      code, output = send_cluster_request_with_token(
        session, cluster_name, "get_cib", false, {}, true, nil, username
      )
    end
    $logger.info(code)
    if code != 200
      $logger.info "Error: unable to load cib"
      $logger.info output
      return
    end

    doc = REXML::Document.new(output)

    cos.each {|co|
      prop_found = false
      doc.elements.each("cib/configuration/crm_config/cluster_property_set/nvpair[@name='#{co.configname}']") { |e|
      	co.value = e.attributes["value"]
      	prop_found = true
      }
      if prop_found == false
      	co.value = co.default
      end
    }
  end

  def self.getDefaultValues(cos)
    metadata = `#{PENGINE} metadata`
    doc = REXML::Document.new(metadata)

    cos.each { |co|
      doc.elements.each("resource-agent/parameters/parameter[@name='#{co.configname}']/content") { |e|
	co.default = e.attributes["default"]
	break
      }
    }
  end

  def checked(option)
    case type
    when "radio"
      val = value
      if option == "Yes"
	if val == "true"
	  return "checked"
	end
      else
	if val == "false"
	  return "checked"
	end
      end
    when "check"
      if value == "true" || value == "on"
	return "checked"
      else
	return ""
      end
    when "dropdown"
      if value == option
	return "selected"
      end
    end
  end

  def html
    paramname = "config[#{configname}]"
    hidden_paramname = "hidden[#{configname}]"
    case type
    when "int"
      return "<input name=\"#{paramname}\" value=\"#{value}\" type=text size=#{size}>"
    when "str"
      return "<input name=\"#{paramname}\" value=\"#{value}\" type=text size=#{size}>"
    when "radio"
      ret = ""
      options.each {|option|
	ret += "<input type=radio #{checked(option)} name=\"#{paramname}\" value=\"#{option}\">#{option}"
      }
      return ret
    when "check"
      ret = "<input type=checkbox name=\"#{paramname}\" " + self.checked(nil) + ">"
      ret += "<input type=hidden name=\"#{hidden_paramname}\" value=\"off\">"
      return ret
    when "dropdown"
      ret = "<select name=\"#{paramname}\">"
      options.each {|key, option|
	ret += "<option #{checked(key)} value=\"#{key}\">#{option}</option>"
      }
      ret += "</select>"
      return ret
    end
  end
end

helpers do
  def h(text)
    Rack::Utils.escape_html(text)
  end

  def nl2br(text)
    text.gsub(/\n/, "<br>")
  end
end
