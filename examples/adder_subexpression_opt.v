module adder_subexpression (clk, a, b, c, d, out1, out2);
  input clk;
  input [7:0] a;
  input [7:0] b;
  input [7:0] c;
  input [7:0] d;
  output [7:0] out1;
  output [7:0] out2;
  wire [7:0] symrtlo_sub_0;
  assign symrtlo_sub_0 = (a + b);
  assign out1 = (symrtlo_sub_0 * c);
  assign out2 = (symrtlo_sub_0 + d);
endmodule