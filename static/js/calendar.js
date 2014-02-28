function createCalendar(user)
{
  var width = 960,
      height = 136,
      cellSize = 17; // cell size

  var day = d3.time.format("%w"),
      week = d3.time.format("%U"),
      percent = d3.format(".1%"),
      format = d3.time.format("%Y-%m-%d");

  var color = d3.scale.quantize()
      .domain([0, 5])
      .range(d3.range(11).map(function(d) { return "q" + d + "-11"; }));

  var tip = d3.tip()
        .direction('e')
        .offset([-5, 5])
        .attr('class', 'd3-tip')
        .html(function(d) { return data[d].note });

  var svg = d3.select(".calendar_" + user.id).selectAll("svg")
      .data([2014])
    .enter().append("svg")
      .attr("width", width)
      .attr("height", height)
      .attr("class", "calendar")
    .append("g")
      .attr("transform", "translate(25, 2)")
      // .attr("transform", "translate(" + ((width - cellSize * 53) / 2) + "," + (height - cellSize * 7 - 1) + ")")
    .call(tip);

  svg.append("svg:a")
      .attr("xlink:href", user.username_url)
    .append("text")
      .attr("transform", "translate(-8," + cellSize * 3.5 + ")rotate(-90)")
      .attr("class", "yaxis-label")
      .style("text-anchor", "middle")
      .text(user.username);

  var rect = svg.selectAll(".day")
      .data(function(d) { return d3.time.days(new Date(d, 0, 1), new Date(d + 1, 0, 1)); })
    .enter().append("rect")
      .attr("class", "day")
      .attr("width", cellSize)
      .attr("height", cellSize)
      .attr("x", function(d) { return week(d) * cellSize; })
      .attr("y", function(d) { return day(d) * cellSize; })
      .datum(format)

  rect.append("date")
      .text(function(d) { return d });

  svg.selectAll(".month")
      .data(function(d) { return d3.time.months(new Date(d, 0, 1), new Date(d + 1, 0, 1)); })
    .enter().append("path")
      .attr("class", "month")
      .attr("d", monthPath);

  var data = user.data;

  // This line breaks if data is empty (can't return d in null)
  var rect = rect.filter(function(d) { return d in data; });

  rect.attr("class", function(d) { return "day " + color(data[d].mood); })
    .select("title")
      .text(function(d) { return d + ": " + percent(data); });

  rect.append("note")
    .text(function(d) { return data[d].note });

  rect.on('mouseover', tip.show)
    .on('mouseout', tip.hide);

  d3.select(self.frameElement).style("height", "2910px");

  function monthPath(t0) {
    var t1 = new Date(t0.getFullYear(), t0.getMonth() + 1, 0),
        d0 = +day(t0), w0 = +week(t0),
        d1 = +day(t1), w1 = +week(t1);
    return "M" + (w0 + 1) * cellSize + "," + d0 * cellSize
        + "H" + w0 * cellSize + "V" + 7 * cellSize
        + "H" + w1 * cellSize + "V" + (d1 + 1) * cellSize
        + "H" + (w1 + 1) * cellSize + "V" + 0
        + "H" + (w0 + 1) * cellSize + "Z";
  }
}