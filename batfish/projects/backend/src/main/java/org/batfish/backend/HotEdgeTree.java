package org.batfish.backend;

import com.google.common.collect.ImmutableSet;
import org.batfish.common.plugin.DataPlanePlugin;
import org.batfish.config.Settings;
import org.batfish.datamodel.*;
import org.batfish.datamodel.collections.NodeInterfacePair;
import org.batfish.datamodel.flow.*;
import org.batfish.dataplane.TracerouteEngineImpl;
import org.batfish.main.Batfish;

import java.io.File;
import java.io.IOException;
import java.nio.charset.Charset;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.*;

import java.util.stream.Collectors;

public class HotEdgeTree {

    class HotEdgeNode{
        Edge edge;
        List<HotEdgeNode> childrens = new ArrayList<>();

        HotEdgeNode(Edge edge){ this.edge = edge; }
        HotEdgeNode(){}
    }

    private Batfish batfish;
    private Settings settings;
    private SortedMap<String, Configuration> configurations;

    private String ingressNode;
    private Ip ip;
    private int maxFailure;

    HotEdgeTree(String configPath, int maxFailure){
        Path containerPath = Paths.get("/tmp/containers/");

        List<String> fullConfigs = new ArrayList<>();

        for(File file : new File(configPath).listFiles()){
            if(file.isFile()) {
                fullConfigs.add(file.getAbsolutePath());
            }
        }

        this.maxFailure = maxFailure;
        batfish = BatfishHelper.getBatfishFromTestrigText(containerPath, fullConfigs.toArray(new String[fullConfigs.size()]));
        settings = batfish.getSettings();
        configurations = batfish.loadConfigurations();
    }

    void outputAllHotEdges(String outputPath){
        Topology topology = batfish.getEnvironmentTopology();
        Set<NodeInterfacePair> topoInterface = new HashSet<>();
        for(Edge edge : topology.getEdges()){
            topoInterface.add(edge.getHead());
            topoInterface.add(edge.getTail());
        }

        Set<NodeInterfacePair> edgeInterface = new HashSet<>();
        for(Map.Entry<String, Configuration> entry : configurations.entrySet()){
            String name = entry.getKey();
            Configuration configuration = entry.getValue();
            for(String interfaceName : configuration.getAllInterfaces().keySet()){
                NodeInterfacePair pair = new NodeInterfacePair(name, interfaceName);
                if(!topoInterface.contains(pair)){
                    edgeInterface.add(pair);
                }
            }
        }

        Path fileHotEdge = Paths.get(outputPath);
        File f = new File(fileHotEdge.toString());
        try {
            f.createNewFile();
            Files.write(fileHotEdge, new ArrayList<String>(), Charset.forName("UTF-8"));
        } catch (IOException e) {
            System.out.println("IOException when trying to create the file: " + fileHotEdge + "; " + e);
        }

        for(String source : configurations.keySet()){
            for(NodeInterfacePair pair : edgeInterface){
                String dest = pair.getHostname();
                String destInterface = pair.getInterface();
                Ip destIp = configurations.get(dest).getAllInterfaces().get(destInterface).getAddress().getIp();
                Map<Edge, Integer> map = getAllHotEdge(source, destIp);

                List<Edge> list = new ArrayList<>(map.keySet()).stream().sorted().collect(Collectors.toList());
                String line = source + ":" + dest + ":" + destInterface + ":" +
                        list.stream().map(Objects::toString).collect(Collectors.joining(",")) + "\n";
                System.out.println(line);

                try {
                    Files.write(Paths.get(outputPath), line.getBytes(), StandardOpenOption.APPEND);
                } catch (IOException e) {
                    System.out.println("IOException when trying to write to file: " + outputPath + "; " + e);
                }
            }
        }
    }

    private Map<Edge, Integer> getAllHotEdge(String ingressNode, Ip ip){
        this.ingressNode = ingressNode;
        this.ip = ip;

        HotEdgeNode root = new HotEdgeNode();
        dfs(root, new ArrayList<>());
        return bfs(root);
    }

    private void dfs(HotEdgeNode node, List<Edge> blackListEdges){
        if(blackListEdges.size() > this.maxFailure){
            return;
        }

        Topology topology = batfish.getEnvironmentTopology();
        topology.prune(new TreeSet<>(blackListEdges), null, null);

        List<Edge> edges = getPath(ingressNode, ip, topology);
        for(Edge edge : edges){
            HotEdgeNode hotEdgeNode = new HotEdgeNode(edge);
            node.childrens.add(hotEdgeNode);
            blackListEdges.add(edge);
            dfs(hotEdgeNode,blackListEdges);
            blackListEdges.remove(blackListEdges.size()-1);
        }
    }

    private List<Edge> getPath(String ingressNode, Ip ip, Topology topology){
        List<Edge> edges = new ArrayList<>();

        DataPlanePlugin.ComputeDataPlaneResult dpResult = batfish.getDataPlanePlugin().computeDataPlane(false, configurations, topology);
        DataPlane dp = dpResult._dataPlane;

        // Construct flows
        Flow flow =
                Flow.builder()
                        .setDstIp(ip)
                        .setIngressNode(ingressNode)
                        .setTag("TAG")
                .build();

        // Compute flow traces
        SortedMap<Flow, List<Trace>> traces =
                TracerouteEngineImpl.getInstance()
                        .buildFlows(dp, ImmutableSet.of(flow), dp.getFibs(), false);

        assert traces.size() == 1;


        for(List<Trace> trace : traces.values()){
            for(Trace singleTrace : trace){
                NodeInterfacePair fromInterface = null, toInterface = null;

                for(Hop hop : singleTrace.getHops()){
                    for(Step<?> step : hop.getSteps()){
                        if(step instanceof ExitOutputIfaceStep){
                            ExitOutputIfaceStep exitOutputIfaceStep = (ExitOutputIfaceStep)step;
                            fromInterface = exitOutputIfaceStep.getDetail().getOutputInterface();
                        }
                        if(step instanceof EnterInputIfaceStep){
                            EnterInputIfaceStep enterInputIfaceStep = (EnterInputIfaceStep)step;
                            toInterface = enterInputIfaceStep.getDetail().getInputInterface();
                            assert fromInterface != null;
                            edges.add(new Edge(fromInterface, toInterface));
                        }
                    }
                }
            }
        }
        return edges;
    }

    private Map<Edge, Integer>  bfs(HotEdgeNode root) {
        Deque<HotEdgeNode> queue = new LinkedList<>();
        Map<Edge, Integer> map = new HashMap<>();
        queue.add(root);
        int level = -1;
        while (!queue.isEmpty()) {
            int size = queue.size();
            for (int i = 0; i < size; i++) {
                HotEdgeNode node = queue.pollFirst();
                Edge edge = node.edge;
                if(edge != null){
                    if (edge.getNode1().compareTo(edge.getNode2()) > 0) {
                        edge = edge.reverse();
                    }
                    if (!map.containsKey(edge)) {
                        map.put(edge, level);
                    }
                }
                if(node.childrens.size() > 0){
                    queue.addAll(node.childrens);
                }
            }
            level++;
        }
        return map;
    }

    public static void main(String[] args) {
        String configPath = "/home/miracle/config2spec/scenarios/uscarrier/bgp/configs1";
        String outputPath = "/home/miracle/config2spec/scenarios/uscarrier/bgp/Layer0HotEdges.txt";
        int maxFailure = 0;

        new HotEdgeTree(configPath, maxFailure).outputAllHotEdges(outputPath);
    }
}
