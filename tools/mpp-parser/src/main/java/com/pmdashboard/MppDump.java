package com.pmdashboard;

import com.fasterxml.jackson.databind.ObjectMapper;
import net.sf.mpxj.ProjectFile;
import net.sf.mpxj.ProjectProperties;
import net.sf.mpxj.Relation;
import net.sf.mpxj.Task;
import net.sf.mpxj.reader.UniversalProjectReader;

import java.io.File;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

public class MppDump {
  public static void main(String[] args) throws Exception {
    if (args.length != 1) {
      System.err.println("Usage: MppDump <file.mpp>");
      System.exit(1);
    }

    ProjectFile project = new UniversalProjectReader().read(new File(args[0]));
    ProjectProperties properties = project.getProjectProperties();

    Map<String, Object> payload = new LinkedHashMap<>();
    payload.put("title", firstNonBlank(properties.getProjectTitle(), new File(args[0]).getName()));
    payload.put("current_finish_date", toIsoDate(properties.getFinishDate()));
    payload.put("baseline_finish_date", toIsoDate(properties.getBaselineFinish()));

    List<Map<String, Object>> tasks = new ArrayList<>();
    for (Task task : project.getTasks()) {
      if (task == null || task.getName() == null || task.getName().isBlank() || Boolean.TRUE.equals(task.getSummary())) {
        continue;
      }

      Map<String, Object> item = new LinkedHashMap<>();
      item.put("unique_id", task.getUniqueID());
      item.put("outline_level", task.getOutlineLevel());
      item.put("outline_path", task.getOutlineNumber());
      item.put("name", task.getName());
      item.put("start_date", toIsoDate(task.getStart()));
      item.put("finish_date", toIsoDate(task.getFinish()));
      item.put("baseline_start_date", toIsoDate(task.getBaselineStart()));
      item.put("baseline_finish_date", toIsoDate(task.getBaselineFinish()));
      item.put("percent_complete", task.getPercentageComplete() == null ? 0.0 : task.getPercentageComplete().doubleValue());
      item.put("critical_flag", Boolean.TRUE.equals(task.getCritical()));
      item.put("milestone_flag", Boolean.TRUE.equals(task.getMilestone()) || isSameDay(task.getStart(), task.getFinish()));
      item.put("predecessor_refs", predecessors(task));
      item.put("notes", task.getNotes());
      tasks.add(item);
    }
    payload.put("tasks", tasks);

    ObjectMapper mapper = new ObjectMapper();
    System.out.println(mapper.writeValueAsString(payload));
  }

  private static String firstNonBlank(String... values) {
    for (String value : values) {
      if (value != null && !value.isBlank()) {
        return value;
      }
    }
    return "Untitled Project";
  }

  private static String toIsoDate(LocalDateTime value) {
    if (value == null) {
      return null;
    }
    LocalDate localDate = value.toLocalDate();
    return localDate.toString();
  }

  private static String predecessors(Task task) {
    List<Relation> predecessors = task.getPredecessors();
    if (predecessors == null || predecessors.isEmpty()) {
      return null;
    }
    return predecessors.stream()
      .map(relation -> {
        Task predecessorTask = relation.getTargetTask();
        if (predecessorTask == null || predecessorTask.getUniqueID() == null) {
          return relation.getType().name();
        }
        return predecessorTask.getUniqueID() + ":" + relation.getType().name();
      })
      .collect(Collectors.joining(", "));
  }

  private static boolean isSameDay(LocalDateTime start, LocalDateTime finish) {
    if (start == null || finish == null) {
      return false;
    }
    return start.toLocalDate().equals(finish.toLocalDate());
  }
}
